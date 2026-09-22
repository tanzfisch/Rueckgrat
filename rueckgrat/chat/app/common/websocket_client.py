import asyncio
import json
import websockets
from typing import Callable, Optional, List
from websockets.connection import State
import ssl
import inspect
from typing import Awaitable, Callable, Union

from .utils import Utils
from .logger import get_logger
logger = get_logger()

class WebSocketClient:
    incoming_message_handlers: List[Callable[[dict], Union[Awaitable[None], None]]] = []

    def __init__(self, uri: str, server_cert: Optional[str] = None):
        self.server_cert = server_cert
        self.uri = uri
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._send_queue = asyncio.Queue()

        self._receive_task = None
        self._send_task = None

    def is_connected(self):
        return (
            self._running
            and self.ws is not None
            and self.ws.state == State.OPEN
            and self._receive_task is not None
            and not self._receive_task.done()
        )
    
    def unregister_incomming_message(self, callback: Callable[[dict], None]):
        if callback in self.incoming_message_handlers:
            self.incoming_message_handlers.remove(callback)

    def register_incomming_message(self, callback: Callable[[dict], None]):
        self.incoming_message_handlers.append(callback)

    async def connect(self, token: Optional[str] = None):
        logger.debug(f"connect with {self.uri}")
        if self.is_connected():
            return
        start = asyncio.get_running_loop().time()
        timeout = 60 * 10
        delay = 1.0
        while True:
            try:
                headers = [("Authorization", f"Bearer {token}")] if token else []
                if self.uri.startswith("wss://"):
                    ssl_context = ssl.create_default_context()
                    if self.server_cert:
                        ssl_context.load_verify_locations(self.server_cert)
                    self.ws = await websockets.connect(self.uri, ssl=ssl_context, additional_headers=headers, ping_interval=30, ping_timeout=60)
                else:
                    self.ws = await websockets.connect(self.uri, additional_headers=headers, ping_interval=30, ping_timeout=60)
                self._running = True
                self.loop = asyncio.get_running_loop()
                logger.info(f"succesfully connected to {self.uri}")

                if self._receive_task and not self._receive_task.done():
                    self._receive_task.cancel()
                self._receive_task = asyncio.create_task(self._receive_loop())

                if self._send_task and not self._send_task.done():
                    self._send_task.cancel()
                self._send_task = asyncio.create_task(self._send_loop())
                return
            except Exception as e:
                self._running = False
                if asyncio.get_running_loop().time() - start > timeout:
                    logger.error(f"timeout while trying to connect with {self.uri} after {timeout/60}min")
                    raise TimeoutError(f"WS connect timeout ({timeout/60}min)") from e
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _receive_loop(self):
        try:
            while self._running:
                msg = await self.ws.recv()
                await self._on_incomming_websocket(json.loads(msg))
        except Exception as e:
            logger.error(f"failed to receive ws from {self.uri}: {repr(e)}")
        finally:
            self._running = False

    async def _send_loop(self):
        try:
            while self._running:
                msg = await self._send_queue.get()
                if self.is_connected():
                    await self.ws.send(msg)
                self._send_queue.task_done()
        except Exception as e:
            logger.error(f"failed to send ws to {self.uri}: {repr(e)}")
        finally:
            self._running = False   

    async def _on_incomming_websocket(self, msg: dict):
        async def _run(func):
            try:
                result = func(msg)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.error(f"failed to handle incoming message in {func!r}: {e!r}")

        await asyncio.gather(*(_run(f) for f in list(self.incoming_message_handlers)))

    def send_message(self, msg: str):
        if not self.is_connected():
            logger.error(f"Websocket not connected")
            return
        self._send_queue.put_nowait(msg)

    async def close(self):
        self._running = False
        if self.is_connected():
            await self.ws.close()