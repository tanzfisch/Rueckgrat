import asyncio
import json
import websockets
from typing import Callable, Optional, List
from websockets.connection import State
from websockets.exceptions import InvalidStatus
import ssl
import inspect
from typing import Awaitable, Callable, Union

from .utils import Utils
from .logger import get_logger
logger = get_logger()

class WebSocketClient:
    def __init__(self, uri: str, server_cert: Optional[str] = None, max_retry_delay: float = 30):
        self.max_retry_delay = max_retry_delay  # s, upper bound of the reconnect backoff
        # per instance, so several clients (e.g. one per node) don't share handlers
        self.incoming_message_handlers: List[Callable[[dict], Union[Awaitable[None], None]]] = []
        self.disconnect_handlers: List[Callable[[], None]] = []
        self.state_handlers: List[Callable[[str], None]] = []
        self._lost = False  # an established connection dropped and is not back yet
        self._supervisor_task: Optional[asyncio.Task] = None
        self._stopped = False
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

    def register_disconnect(self, callback: Callable[[], None]):
        """called whenever an established connection is lost (start() mode)"""
        self.disconnect_handlers.append(callback)

    def register_state_change(self, callback: Callable[[str], None]):
        """start() mode: "lost" when an established connection drops, "reconnected" when it is back,
        "rejected" when the peer refuses the token (401/403, no more retries), "stopped" on close()"""
        self.state_handlers.append(callback)

    def _notify_state(self, state: str):
        for cb in list(self.state_handlers):
            try:
                cb(state)
            except Exception as e:
                logger.error(f"state handler {cb!r} failed: {e!r}")

    def _notify_disconnect(self):
        for cb in list(self.disconnect_handlers):
            try:
                cb()
            except Exception as e:
                logger.error(f"disconnect handler {cb!r} failed: {e!r}")

    async def connect(self, token: Optional[str] = None, timeout: Optional[float] = 60 * 10):
        """connect once, retrying with backoff. timeout=None retries forever"""
        if self.is_connected():
            return
        start = asyncio.get_running_loop().time()
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
                if isinstance(e, InvalidStatus) and e.response.status_code in (401, 403):
                    raise  # wrong or expired token, retrying won't help
                if timeout is not None and asyncio.get_running_loop().time() - start > timeout:
                    logger.error(f"timeout while trying to connect with {self.uri} after {timeout/60}min")
                    raise TimeoutError(f"WS connect timeout ({timeout/60}min)") from e
                logger.info(f"connecting to {self.uri} failed ({e!r}), retrying in {delay:.0f}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_retry_delay)

    async def _receive_loop(self):
        try:
            while self._running:
                msg = await self.ws.recv()
                await self._on_incomming_websocket(json.loads(msg))
        except websockets.exceptions.ConnectionClosed as e:
            # peer went away (restart, shutdown, network) - expected, the supervisor reconnects
            logger.info(f"connection to {self.uri} closed (code {e.code})")
        except asyncio.CancelledError:
            raise
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

    def send_message(self, msg: str) -> bool:
        """False if not connected, the message is not queued then"""
        if not self.is_connected():
            logger.error(f"Websocket not connected")
            return False
        self._send_queue.put_nowait(msg)
        return True

    def start(self, token: Optional[str] = None):
        """keep the connection alive in the background: connect whenever the peer
        becomes reachable and reconnect after it goes away. returns immediately"""
        if self._supervisor_task and not self._supervisor_task.done():
            return
        self._stopped = False
        self._supervisor_task = asyncio.create_task(self._supervise(token))

    async def _supervise(self, token: Optional[str]):
        while not self._stopped:
            try:
                await self.connect(token, timeout=None)
                if self._lost:
                    self._lost = False
                    logger.info(f"reconnected to {self.uri}")
                    self._notify_state("reconnected")
                tasks = [t for t in (self._receive_task, self._send_task) if t]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if self._stopped:
                    break
                logger.info(f"{self.uri} not reachable anymore, waiting for it to come back")
                self._running = False
                self._lost = True
                self._notify_disconnect()
                self._notify_state("lost")
            except asyncio.CancelledError:
                raise
            except InvalidStatus as e:
                # connect() only raises it for 401/403
                logger.error(f"{self.uri} rejected the token ({e.response.status_code}), not reconnecting")
                self._stopped = True
                self._lost = False
                self._notify_state("rejected")
            except Exception as e:
                logger.error(f"connection supervisor error for {self.uri}: {e!r}")
            self._running = False
            for t in (self._receive_task, self._send_task):
                if t and not t.done():
                    t.cancel()
            try:
                if self.ws is not None:
                    await self.ws.close()
            except Exception:
                pass
            await asyncio.sleep(1)

    async def close(self):
        self._stopped = True
        if self._supervisor_task and not self._supervisor_task.done():
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
        self._running = False
        self._lost = False
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        self._notify_state("stopped")