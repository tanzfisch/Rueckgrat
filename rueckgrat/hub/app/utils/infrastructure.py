
import json
import os
import requests
from tqdm import tqdm
from urllib.parse import urlparse
from requests.models import Response
from pathlib import Path
from typing import Optional, Dict, Callable
from dataclasses import dataclass
from ..jobs.image_job import ImageRequest

from app.common import get_logger, ChatRequestLlama, DownloadQueue, Utils, WebSocketClient
logger = get_logger()

INFRASTRUCTURE_CONFIG_PATH = Path("/hub/config/infrastructure.json")

@dataclass
class ServerResult:
    url: str
    ok: bool
    error: Optional[str] = None

@dataclass
class StatusResult:
    def __init__(self, servers: list[ServerResult] = None):
        self.nodes = servers if servers else []

    nodes : list[ServerResult]

class WebSocketClientNode(WebSocketClient):
    def __init__(self, addr: str, port: int, type: str):
        self.addr = addr
        self.port = port
        self.type = type
        self.uri = f"ws://{self.addr}:{self.port}/ws"
        logger.debug(f"connecting to node at {self.uri}")
        super().__init__(self.uri)

class Infrastructure:
    callback_handlers: Dict[int, Callable[[str], None]] = {}

    def __init__(self):
        if not INFRASTRUCTURE_CONFIG_PATH.exists():
            logger.error(f"no infrastructure config found at {INFRASTRUCTURE_CONFIG_PATH}")
            return

        with open(INFRASTRUCTURE_CONFIG_PATH, "r") as f:
            data = json.load(f)

        self.hosts = data["hosts"]
        self.nodes: dict[str, WebSocketClientNode] = {}

        self.download_queue = DownloadQueue()

    async def connect_nodes(self):
        for host in self.hosts:
            if "node" in host:
                node = host["node"]
                if "services" in node:
                    services = node["services"]
                    for service in services:
                        websocket_node = WebSocketClientNode(host["addr"], node["port"], service["type"])
                        await websocket_node.connect()
                        self.nodes[service["type"]] = websocket_node
                        logger.debug(f"found {service['type']} service at {host['addr']}:{node['port']}")

        if not "text_to_text" in self.nodes:
            logger.error("couldn't find text_to_text generator")
        else:
            node = self.nodes["text_to_text"]
            node.register_incomming_message(self._on_incomming_message)            

        if not "text_to_image" in self.nodes:
            logger.warning("couldn't find text_to_image generator")        

    def get_status(self) -> StatusResult:
        result = StatusResult()

        for host in self.hosts:

            if "node" in host:
                node = host["node"]
                url = f"http://{host['addr']}:{node['port']}/health"

                try:
                    response = requests.get(url, timeout=1)

                    ok = response.status_code == 200 \
                    and response.json() == {"status": "ok"} \
                    and response.headers.get("content-type", "").startswith("application/json")

                    if ok:
                        result.nodes.append(ServerResult(url, ok))
                    else:
                        result.nodes.append(ServerResult(url, ok, error=response["status"]))
                                    
                except Exception as e:
                    result.nodes.append(ServerResult(url, False, error=repr(e)))

        return result
    
    # TODO need to begin working on a common module that can be shared across applications
    def _download_file(self, url, filepath) -> int:
        if os.path.exists(filepath):
            return
        
        r = requests.get(url, stream=True)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", 0))

        with open(filepath, "wb") as f:
            with tqdm(total=total_size, unit="B", unit_scale=True, desc=f"Downloading {url}", unit_divisor=1024) as pbar:
                for chunk in r.iter_content(chunk_size=64*1024):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

        return total_size    

    def _download_from_url(self, url: str, dst_path: str) -> int:
        logger.debug(f"download {url} -> {dst_path}")

        target_path = Path("/node") / dst_path
        target_path.mkdir(parents=True, exist_ok=True)

        filename = os.path.basename(urlparse(url).path)
        target_filepath = target_path / filename

        if os.path.exists(target_filepath):
            target_filepath.unlink(missing_ok=True)

        return self._download_file(url, target_filepath)

    def image(self, image_request: ImageRequest) -> str:
        if not "text_to_image" in self.nodes:
            logger.error("no text to image generator available")
            return None
        
        node = self.nodes["text_to_image"]
        url_image_request = f"http://{node.addr}:{node.port}/image"

        try:
            response = requests.post(
                url_image_request,
                json=image_request.model_dump(),
                timeout=240,
            )
        
            if response.status_code == 200:
                data = response.json()
                filepath = Path(data.get("output", []))
                if not filepath:
                    logger.error("got invalid file path from image response")
                    return None
            else:
                logger.error(f"failed image request: {response.status_code} {response.reason}")
                return None

        except Exception as e:
            logger.error(f"failed to get a image response {repr(e)}")
            return None        

        return str(filepath)

    def download(self, source_path: str, download_path: str, asynchronous: bool = True, callback=None, max_retry: int = 5, force_download: bool=False):
        node = self.nodes["text_to_image"] # not sure about this. how do we know from which node to download?
        url = f"http://{node.addr}:{node.port}/downloads{source_path}"
        if asynchronous:
            self.download_queue.add(
                url=url, 
                download_path=download_path,
                max_retry=max_retry,
                force_download=force_download,
                callback=callback)
        else:
            self.download_queue.download(
                url=url, 
                download_path=download_path, 
                force_download=force_download)

    def _on_incomming_message(self, message: str):
        try:
            data = json.loads(message)
            conversation_id = data.get("conversation_id")

            if conversation_id in self.callback_handlers:
                self.callback_handlers[conversation_id](message)
                if "response" in data:
                    del self.callback_handlers[conversation_id]

        except Exception as e:
            logger.error(f"failed to handle incomming message from node {repr(e)}")

    def chat(self, messages: list, temperature: float, seed: int, conversation_id: int = -1, stream: bool = False, callback = None, max_new_tokens: int = 512, context_size: int=8192) -> str:
        try:
            chat_request = ChatRequestLlama(
                messages=messages,
                temperature=temperature,
                seed=seed,
                max_new_tokens=max_new_tokens,
                context_size=context_size,
                stream=stream,
                conversation_id=conversation_id
            )

            #logger.debug(f"sending query to llm:\n{Utils.pretty_print(chat_request.model_dump())}")

            node = self.nodes["text_to_text"]

            if stream:
                if not callback:
                    logger.error(f"need callback for streaming")
                    return None
                
                self.callback_handlers[conversation_id] = callback
                payload = {"chat": chat_request.model_dump()}
                node.send_message(json.dumps(payload))
            else:
                url = f"http://{node.addr}:{node.port}/chat"
                response = requests.post(
                    url,
                    json=chat_request.model_dump(),
                    timeout=240,
                )
            
                if response.status_code == 200:
                    data = response.json()
                    return data.get("content", "")

        except Exception as e:
            logger.error(f"failed to get a chat response {repr(e)}")

        return None

    def get_model_url(self, model_name) -> Response:
        node = self.nodes["text_to_text"] # we can use any node here
        url = f"http://{node.addr}:{node.port}/models/{model_name}/url"
        logger.debug(f"get_model_url for {model_name} from {url}")
        
        try:
            response = requests.get(
                url,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("model_urls", [])

            logger.error(f"failed to get_model_url response {response.status_code} {response.reason}")
            return []

        except Exception as e:
            logger.error(f"failed to get_model_url response {repr(e)}")

        return []