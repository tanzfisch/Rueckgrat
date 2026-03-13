import asyncio
import websockets
from typing import Callable, Optional
from websockets.connection import State

class WebSocketClient:
    def __init__(self, uri: str):
        self.uri = uri
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.on_message: Optional[Callable[[str], None]] = None
        self._running = False

    def set_on_message(self, callback: Callable[[str], None]):
        """Set function to call when message arrives from server"""
        self.on_message = callback

    def is_connected(self):
        return self._running
    
    async def connect(self):
        self.ws = await websockets.connect(self.uri)
        self._running = True
        asyncio.create_task(self._receive_loop())

    async def _receive_loop(self):
        try:
            while self._running:
                msg = await self.ws.recv()
                if self.on_message:
                    self.on_message(msg)
                else:
                    print("Server:", msg)
        except Exception as e:
            print("Receive error:", e)
        finally:
            self._running = False

    async def send_message(self, msg: str):
        """Send message – returns immediately"""
        if not self.ws or self.ws.state != State.OPEN:
            raise RuntimeError("Not connected")
        await self.ws.send(msg)

    async def close(self):
        self._running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
