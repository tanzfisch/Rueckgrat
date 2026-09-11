import asyncio
import json
import queue
import ssl
import threading

import sounddevice as sd
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
        self.uri = uri  # wss://host:port/ws/audio
        self.token = token
        self.cert = cert
        self._q = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._ws = None
        self._loop = None
        self._stream = None
        self._send_thread = None
        self.on_message = on_message

    def start(self):
        if self._send_thread and self._send_thread.is_alive():
            return
        self._stop.clear()
        self._send_thread = threading.Thread(target=self._thread_main, daemon=True)
        self._send_thread.start()
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
            callback=self._on_audio,
        )
        self._stream.start()

    def stop(self):
        self._stop.set()
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
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

    def _on_audio(self, indata, frames, time_info, status):        
        if self._stop.is_set():
            return
        try:
            self._q.put_nowait(bytes(indata))
        except queue.Full:
            pass

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
        kwargs = {
            "additional_headers": {"Authorization": f"Bearer {self.token}"},
        }
        ctx = self._ssl_context()
        if ctx is not None:
            kwargs["ssl"] = ctx

        try:
            async with websockets.connect(self.uri, **kwargs) as ws:
                self._ws = ws
                await ws.send(json.dumps({
                    "type": "audio.start",
                    "sample_rate": SAMPLE_RATE,
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
                print(f"audio ws error: {e}")

    async def _sender(self, ws):
        while not self._stop.is_set():
            try:
                chunk = self._q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            await ws.send(chunk)