import os
import asyncio
import json
import websockets
from typing import Callable, Optional
from websockets.connection import State
from pathlib import Path
import configparser
import ssl

from common import Logger
logger = Logger(__name__).get_logger()

class WebSocketClient:
    def __init__(self, uri: str):
        config = configparser.ConfigParser()
        config_path = Path("~/.config/Rueckgrat/rueckgrat.conf").expanduser()

        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.touch()   

        with open(config_path, encoding="utf-8-sig") as f:
            config.read_file(f)        

        self.server_cert = config.get('frontend', 'server_cert', fallback="no")
        self.server_cert = os.path.expanduser(self.server_cert)

        self.uri = uri
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.on_message: Optional[Callable[[dict], None]] = None
        self._running = False

    def set_on_message(self, callback: Callable[[dict], None]):
        self.on_message = callback

    def is_connected(self):
        return self._running
    
    async def connect(self):
        try:
            ssl_context = ssl.create_default_context()
            ssl_context.load_verify_locations(self.server_cert)
            
            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            self._running = True
            asyncio.create_task(self._receive_loop())
        except Exception as e:
            logger.error(f"failed to connect ws: {repr(e)}")
            self._running = False
            raise

    async def _receive_loop(self):
        try:
            while self._running:
                msg = await self.ws.recv()
                if self.on_message:
                    logger.debug(msg)
                    self.on_message(json.loads(msg))
        except Exception as e:
            logger.error(f"failed to receive ws: {repr(e)}")
        finally:
            self._running = False

    async def send_message(self, msg: str):
        if not self.ws or self.ws.state != State.OPEN:
            logger.error(f"Websocket not connected")
            return
        await self.ws.send(msg)

    async def close(self):
        self._running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
