import array
import asyncio
import json
import math
import queue
import ssl
import threading

import flet as ft
import flet_audio_recorder as far
import websockets
from websockets.exceptions import InvalidStatus

from app.common import get_logger
from .keep_alive import KeepAlive
logger = get_logger()

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
BLOCK_MS = 20
BLOCKSIZE = SAMPLE_RATE * BLOCK_MS // 1000

# while the audio websocket is down the mic keeps recording into a buffer, sent once it is back.
BUFFER_SECONDS = 120                                
BUFFER_BYTES = SAMPLE_RATE * 2 * BUFFER_SECONDS
SEND_PIECE = SAMPLE_RATE * 2
MAX_RETRY_DELAY = 2
RESEND_BYTES = SAMPLE_RATE * 2 * 60

class AudioStreamer:
    def __init__(self, uri: str, token: str, cert=None, on_message=None, language: str = "", transcript_id: int = 0,
                 start_offset: float = 0.0):
        self.uri = uri
        self.language = language  # whisper language code, "" = the hub's stt detects it
        self.transcript_id = transcript_id  # transcribe app (#198): the hub stores the finals there, 0 = nowhere
        self.start_offset = start_offset    # seconds of the transcript before this recording (continued), the clock starts there
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
        self.level = 0.0
        self._buffer = bytearray()
        self._queued_buffer = bytearray()
        self._skip_partials = False
        self._resample_pos = 0.0
        self._captured = 0                      # bytes recorded since start(), the clock of position
        self._finishing = threading.Event()     # finish(): send what is left, then audio.stop
        self._finished = threading.Event()      # the hub closed after audio.stop
        self._stop_sent = False
        self.recorder = far.AudioRecorder(
            configuration=self._recorder_config(SAMPLE_RATE),
            on_stream=self._on_flet_stream,
            on_state_change=lambda e: logger.info("recorder state: %s", getattr(e, "data", e)),
        )

    @staticmethod
    def _recorder_config(rate: int):
        """ echo canceller on the voice call source, so the mic does not hear the AI's speech (Android) """
        return far.AudioRecorderConfiguration(
            encoder=far.AudioEncoder.PCM16BITS,
            sample_rate=rate,
            channels=CHANNELS,
            cancel_echo=True,
            android_configuration=far.AndroidRecorderConfiguration(
                audio_source=far.AndroidAudioSource.VOICE_COMMUNICATION,
            ),
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
            chunk = bytes(indata)
            self._update_level(chunk)
            self._q.put_nowait(chunk)
        except queue.Full:
            pass

    def _update_level(self, chunk: bytes):
        samples = array.array("h", chunk[: len(chunk) // 2 * 2])
        if not samples:
            return
        rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0
        k = 5.0
        rms = (math.exp(k * rms) - 1) / (math.exp(k) - 1)

        db = 20 * math.log10(rms) if rms > 0 else -60.0
        new_level = min(1.0, max(0.0, (db + 60.0) / 60.0))

        # smooth
        alpha = 0.2
        self.level = alpha * new_level + (1 - alpha) * self.level

    def _on_flet_stream(self, e: far.AudioRecorderStreamEvent):
        if self._stop.is_set() or not e.chunk:
            return
        try:
            self._update_level(e.chunk)
            chunk = e.chunk if self.sample_rate == SAMPLE_RATE else self._resample(e.chunk)
            self._q.put_nowait(chunk)
        except queue.Full:
            pass

    def _resample(self, chunk: bytes) -> bytes:
        """ resample down to 16kHz in otder to reduce data to transmit """
        samples = array.array("h", chunk[: len(chunk) // 2 * 2])
        step = self.sample_rate / SAMPLE_RATE
        out = array.array("h")
        pos = self._resample_pos
        while pos < len(samples):
            out.append(samples[int(pos)])
            pos += step
        self._resample_pos = pos - len(samples)
        return out.tobytes()

    @property
    def position(self) -> float:
        """seconds of the recording: start_offset + recorded since start(). the hub tells the times of the finals in the same clock"""
        return self.start_offset + self._captured / (SAMPLE_RATE * 2)

    async def start(self):
        if self._send_thread and self._send_thread.is_alive():
            return
        self._stop.clear()
        self._finishing.clear()
        self._finished.clear()
        self._captured = 0
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
        # while visible and after RECORD_AUDIO (Android 14+): without it the OS silences the mic in the background
        await KeepAlive.set_microphone(True)
        for rate in (16000, 44100):
            started = await self.recorder.start_recording(
                configuration=self._recorder_config(rate),
            )
            logger.info("start_recording rate=%s -> %s", rate, started)
            if started:
                self.sample_rate = rate
                return
        raise RuntimeError("start_recording returned False")

    async def finish(self, timeout: float = 60):
        """a stop that loses nothing: the mic goes off, the audio not sent yet is sent, audio.stop makes the hub transcribe
        the last words and close. then stop(), also when the hub did not answer within timeout seconds"""
        await self._stop_mic()
        self._finishing.set()
        if not await asyncio.to_thread(self._finished.wait, timeout):
            logger.warning("the hub did not finish the audio within %ss, the last words may be missing", timeout)
        await self.stop()

    async def _stop_mic(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        try:
            if self._is_mobile():
                await self.recorder.stop_recording()
        except Exception:
            pass
        await KeepAlive.set_microphone(False)

    async def stop(self):
        self._stop.set()
        await self._stop_mic()
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
        self._buffer.clear()
        self._queued_buffer.clear()

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
        kwargs = {"additional_headers": {"Authorization": f"Bearer {self.token}"}, "ping_interval": 5, "ping_timeout": 5}
        ctx = self._ssl_context()
        if ctx is not None:
            kwargs["ssl"] = ctx
        delay = 0.5
        # the mic queue is emptied all the time, also while connecting, which can hang for seconds
        collector = asyncio.create_task(self._collect())
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.uri, **kwargs) as ws:
                    self._ws = ws
                    delay = 0.5
                    self._stop_sent = False
                    # the first byte sent now is the oldest the hub has not answered (replay) or the next one recorded
                    offset = self.start_offset + (self._captured - len(self._buffer) - len(self._queued_buffer)) / (SAMPLE_RATE * 2)
                    await ws.send(json.dumps({
                        "type": "audio.start",
                        "sample_rate": SAMPLE_RATE,
                        "channels": CHANNELS,
                        "encoding": "pcm_s16le",
                        "language": self.language,
                        **({"transcript_id": self.transcript_id, "offset": offset} if self.transcript_id else {}),
                    }))
                    if self._buffer or self._queued_buffer:
                        logger.info("audio ws back, sending %.1fs of buffered audio", (len(self._queued_buffer) + len(self._buffer)) / SEND_PIECE)
                        self._skip_partials = True
                    sender = asyncio.create_task(self._sender(ws))
                    try:
                        async for message in ws:
                            self._notify(json.loads(message))
                    finally:
                        sender.cancel()
                    if self._stop_sent:     # the hub closed after audio.stop: everything is transcribed
                        self._ws = None
                        self._finished.set()
                        break
            except InvalidStatus as e:
                if e.response.status_code in (401, 403):
                    logger.error("audio ws rejected the token, not reconnecting")
                    self._buffer.clear()
                    self._queued_buffer.clear()
                    break
                logger.error("audio ws error: %s", e)
            except Exception as e:
                if not self._stop.is_set():
                    logger.error("audio ws error: %s", e)
            self._ws = None
            if not self._stop.is_set():
                logger.info("audio ws down, buffering, retry in %.1fs", delay)
                await self._wait(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)
        collector.cancel()

    def _notify(self, message: dict):
        kind = message.get("type")
        if kind == "partial" and self._skip_partials:
            return
        if kind == "final":
            self._skip_partials = False
            self._queued_buffer.clear()  # the hub has transcribed it
        if self.on_message:
            try:
                self.on_message(message)
            except Exception:
                pass

    def _drain(self):
        """mic queue -> buffer. over BUFFER_BYTES everything is discarded and the mic goes off,
        the same as switching it off by hand: nothing of it is sent on a later reconnect"""
        while True:
            try:
                chunk = self._q.get_nowait()
            except queue.Empty:
                return
            if len(self._buffer) + len(chunk) > BUFFER_BYTES:
                logger.warning("audio buffer full (%ss), discarding it and switching the mic off", BUFFER_SECONDS)
                self._buffer.clear()
                self._queued_buffer.clear()
                self._stop.set()
                self._notify({"type": "mic.off"})
                return
            self._buffer.extend(chunk)
            self._captured += len(chunk)

    async def _collect(self):
        while not self._stop.is_set():
            self._drain()
            await asyncio.sleep(0.01)

    async def _wait(self, seconds: float):
        end = self._loop.time() + seconds
        while not self._stop.is_set() and self._loop.time() < end:
            await asyncio.sleep(0.01)

    async def _sender(self, ws):
        replay, self._queued_buffer = self._queued_buffer, bytearray()
        try:
            while replay:
                await self._send(ws, replay)
        finally:
            self._queued_buffer.extend(replay)
        while not self._stop.is_set():
            if not self._buffer:
                if self._finishing.is_set() and self._q.empty():
                    await ws.send(json.dumps({"type": "audio.stop"}))
                    self._stop_sent = True
                    return
                await asyncio.sleep(0.01)
                continue
            await self._send(ws, self._buffer)

    async def _send(self, ws, audio: bytearray):
        piece = bytes(audio[:SEND_PIECE])
        await ws.send(piece)
        del audio[: len(piece)]
        self._queued_buffer.extend(piece)
        del self._queued_buffer[:-RESEND_BYTES]
