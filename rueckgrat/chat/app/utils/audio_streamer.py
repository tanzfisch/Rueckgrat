import asyncio
import json
import queue
import ssl
import threading

import flet as ft
import flet_audio_recorder as far
import websockets

from app.common import get_logger
logger = get_logger()

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
BLOCK_MS = 20
BLOCKSIZE = SAMPLE_RATE * BLOCK_MS // 1000


class AudioStreamer:
    def __init__(self, uri: str, token: str, cert=None, on_message=None):
        self.uri = uri
        self.token = token
        self.cert = cert
        self.on_message = on_message
        self.sample_rate = SAMPLE_RATE
        self._q = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._ws = None
        self._loop = None
        self._stream = None
        self._send_thread = None
        self._page = None
        self.recorder = far.AudioRecorder(
            configuration=far.AudioRecorderConfiguration(
                encoder=far.AudioEncoder.PCM16BITS,
                sample_rate=SAMPLE_RATE,
                channels=CHANNELS,
            ),
            on_stream=self._on_flet_stream,
            on_state_change=lambda e: logger.info("recorder state: %s", getattr(e, "data", e)),
        )

    def attach(self, page: ft.Page):
        self._page = page
        if self._is_mobile() and self.recorder not in page.services:
            page.services.append(self.recorder)
            page.update()

    def _is_mobile(self) -> bool:
        p = getattr(self._page, "platform", None) if self._page else None
        return bool(p and getattr(p, "is_mobile", lambda: False)())

    def _on_audio(self, indata, frames, time_info, status):
        if self._stop.is_set():
            return
        try:
            self._q.put_nowait(bytes(indata))
        except queue.Full:
            pass

    def _on_flet_stream(self, e: far.AudioRecorderStreamEvent):
        if self._stop.is_set() or not e.chunk:
            return
        try:
            self._q.put_nowait(e.chunk)
        except queue.Full:
            pass

    async def start(self):
        if self._send_thread and self._send_thread.is_alive():
            return
        self._stop.clear()
        self._send_thread = threading.Thread(target=self._thread_main, daemon=True)
        self._send_thread.start()
        if self._is_mobile():
            await self._start_flet()
        else:
            self._start_sounddevice()

    def _start_sounddevice(self):
        import sounddevice as sd
        self.sample_rate = SAMPLE_RATE
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
            callback=self._on_audio,
        )
        self._stream.start()

    async def _start_flet(self):
        if self.recorder not in (self._page.services if self._page else []):
            raise RuntimeError("call attach(page) before start()")
        check = getattr(self.recorder, "check_permission", None) or self.recorder.has_permission
        if not await check():
            raise PermissionError("RECORD_AUDIO denied")
        for rate in (16000, 44100):
            started = await self.recorder.start_recording(
                configuration=far.AudioRecorderConfiguration(
                    encoder=far.AudioEncoder.PCM16BITS,
                    sample_rate=rate,
                    channels=CHANNELS,
                ),
            )
            logger.info("start_recording rate=%s -> %s", rate, started)
            if started:
                self.sample_rate = rate
                return
        raise RuntimeError("start_recording returned False")

    async def stop(self):
        self._stop.set()
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        try:
            if self._is_mobile():
                await self.recorder.stop_recording()
        except Exception:
            pass
        if self._ws and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
            except Exception:
                pass
        if self._send_thread:
            self._send_thread.join(timeout=2)
            self._send_thread = None
        self._ws = None
        self._loop = None

    def _ssl_context(self):
        if not self.cert:
            return None
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cafile=str(self.cert))
        return ctx

    def _thread_main(self):
        asyncio.run(self._run_ws())

    async def _run_ws(self):
        self._loop = asyncio.get_running_loop()
        kwargs = {"additional_headers": {"Authorization": f"Bearer {self.token}"}}
        ctx = self._ssl_context()
        if ctx is not None:
            kwargs["ssl"] = ctx
        try:
            async with websockets.connect(self.uri, **kwargs) as ws:
                self._ws = ws
                await ws.send(json.dumps({
                    "type": "audio.start",
                    "sample_rate": self.sample_rate,
                    "channels": CHANNELS,
                    "encoding": "pcm_s16le",
                }))
                sender = asyncio.create_task(self._sender(ws))
                try:
                    async for message in ws:
                        if not self.on_message:
                            continue
                        try:
                            self.on_message(json.loads(message))
                        except Exception:
                            pass
                finally:
                    sender.cancel()
        except Exception as e:
            if not self._stop.is_set():
                logger.error("audio ws error: %s", e)

    async def _sender(self, ws):
        while not self._stop.is_set():
            try:
                chunk = self._q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            await ws.send(chunk)