
import asyncio
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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    def __init__(self, addr: str, port: int):
        self.addr = addr
        self.port = port
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
        self.nodes: list[WebSocketClientNode] = []
        self.node_by_type: dict[str, WebSocketClientNode] = {}

        self.download_queue = DownloadQueue()

    async def connect_nodes(self):
        for host in self.hosts:
            if "node" in host:
                node = host["node"]
                websocket_node = WebSocketClientNode(host["addr"], node["port"])
                self.nodes.append(websocket_node)
                # non-blocking: connects whenever the node comes up, reconnects if it restarts
                websocket_node.start()
                logger.debug(f"connecting with node {host['addr']}:{node['port']} in background")

                if "services" in node:
                    services = node["services"]
                    for service in services:
                        self.node_by_type[service["type"]] = websocket_node
                        logger.debug(f"found service {service['type']} on node {host['addr']}:{node['port']}")

                if "modules" in node:
                    modules = node["modules"]
                    for module in modules:
                        self.node_by_type[module["type"]] = websocket_node
                        logger.debug(f"found module {module['type']} on node {host['addr']}:{node['port']}")  

        if not "text_to_text" in self.node_by_type:
            logger.error("couldn't find text_to_text generator")
        else:
            node = self.node_by_type["text_to_text"]
            node.register_incomming_message(self._on_incomming_message)
            node.register_disconnect(self._fail_pending_streams)

        if not "text_to_image" in self.node_by_type:
            logger.warning("couldn't find text_to_image generator")        

    def get_status(self) -> StatusResult:
        result = StatusResult()
        hosts = [h for h in self.hosts if "node" in h]

        def check(host):
            node = host["node"]
            url = f"http://{host['addr']}:{node['port']}/health"
            try:
                r = requests.get(url, timeout=1)
                ok = (
                    r.status_code == 200
                    and r.json() == {"status": "ok"}
                    and r.headers.get("content-type", "").startswith("application/json")
                )
                err = None if ok else str(r.status_code)
                return ServerResult(url, ok, error=err)
            except Exception as e:
                return ServerResult(url, False, error=repr(e))

        if hosts:
            with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
                futs = [pool.submit(check, h) for h in hosts]
                for f in as_completed(futs):
                    result.nodes.append(f.result())
        return result

    def set_log_level(self, level):
        ok = True
        for host in self.hosts:
            if "node" not in host:
                continue
            node = host["node"]
            url = f"http://{host['addr']}:{node['port']}/log-level/{level}"
            try:
                response = requests.put(url, timeout=5)
                if response.status_code != 200:
                    logger.error(f"failed to set log level - {response.status_code}")
                    ok = False
            except Exception as e:
                logger.error(f"failed to set log level: {repr(e)}")
                ok = False
        return ok
    
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
        if not "text_to_image" in self.node_by_type:
            logger.error("no text to image generator available")
            return None
        
        node = self.node_by_type["text_to_image"]
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

    @staticmethod
    def _error_response(conversation_id: int, error: str) -> str:
        # same shape as a final node response so waiting jobs finish
        return json.dumps({"conversation_id": conversation_id, "response": "", "error": error})

    def _fail_pending_streams(self):
        """connection to the node dropped: in-flight streams will never finish, fail them now"""
        pending = list(self.callback_handlers.items())
        self.callback_handlers.clear()
        for conversation_id, callback in pending:
            logger.error(f"connection lost during stream for conversation {conversation_id}")
            try:
                callback(self._error_response(conversation_id, "connection to node lost"))
            except Exception as e:
                logger.error(f"failed to notify conversation {conversation_id}: {e!r}")

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

    def chat(self, messages: list, temperature: float, seed: int, conversation_id: int = -1, stream: bool = False, callback = None, max_new_tokens: int = 1024, context_size: int=8192) -> str:
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

            node = self.node_by_type["text_to_text"]

            if stream:
                if not callback:
                    logger.error(f"need callback for streaming")
                    return None
                
                if not node.is_connected():
                    logger.error(f"node {node.uri} not connected, failing chat request")
                    callback(self._error_response(conversation_id, "node not connected"))
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

    def download(self, source_path: str, download_path: str, asynchronous: bool = True, callback=None, max_retry: int = 5, force_download: bool=False):
        node = self.node_by_type["text_to_image"] # not sure about this. how do we know from which node to download?
        url = f"http://{node.addr}:{node.port}/downloads/{source_path}"
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

    def get_model_url(self, model_name) -> Response:
        node = self._get_any_node()
        url = f"http://{node.addr}:{node.port}/models/{model_name}/url"
        logger.debug(f"get model urls for {model_name} from {url}")
        
        try:
            response = requests.get(
                url,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("model_urls", [])

            logger.error(f"failed to get model urls {response.status_code} {response.reason}")
            return []

        except Exception as e:
            logger.error(f"failed to get model urls {repr(e)}")

        return []

    def _get_any_node(self):
        if len(self.nodes) == 0:
            logger.error(f"no nodes contacted")

        # prefer a node we are actually connected to
        for node in self.nodes:
            if node.is_connected():
                return node
        return self.nodes[0]

    async def wait_for_any_node(self, poll: float = 1.0):
        """block until at least one node is connected, then return it"""
        while True:
            for node in self.nodes:
                if node.is_connected():
                    return node
            await asyncio.sleep(poll)

    def get_registered_models(self) -> list:
        node = self._get_any_node()
        url = f"http://{node.addr}:{node.port}/models/registered"
        logger.debug(f"get registered models from {url}")

        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.json().get("models", [])
            logger.error(f"failed to get registered models {response.status_code} {response.reason}")
        except Exception as e:
            logger.error(f"failed to get registered models {repr(e)}")
        return []

    def get_model(self, model_name: str) -> Optional[dict]:
        """model info from a node. {} if the node doesn't know it, None if no node is reachable (yet)"""
        node = self._get_any_node()
        url = f"http://{node.addr}:{node.port}/models/{model_name}"
        logger.debug(f"get model for {model_name} from {url}")

        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.json()
            logger.error(f"failed to get model info {response.status_code} {response.reason}")
        except requests.exceptions.ConnectionError:
            # node not started yet - not an error
            logger.info(f"model info for {model_name} not available yet, node {node.addr}:{node.port} not reachable")
            return None
        except Exception as e:
            logger.error(f"failed to get model info {repr(e)}")
        return {}

    def install_model(self, model_name: str, force: bool = False) -> bool:
        if not force and self.is_installed(model_name):
                return True

        model = self.get_model(model_name)
        if model is None:
            logger.info(f"skipping install of {model_name}, no node reachable yet")
            return False
        if not model or not model.get("files"):
            logger.error(f"model {model_name} not registered")
            return False

        files = model["files"]
        install_path = model.get("install_path") or ""
        urls = self.get_model_url(model_name) or []
        url_by_name = {os.path.basename(urlparse(u).path): u for u in urls}

        base = Path("/hub/models")
        ok = True

        for file in files:
            source_url = file["source"]
            source_path = file.get("path") or ""
            filename = os.path.basename(urlparse(source_url).path)
            target_dir = base / install_path / source_path if source_path else base / install_path
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename

            if force and target.exists():
                target.unlink(missing_ok=True)

            url = url_by_name.get(filename, source_url)
            try:
                self._download_file(url, target)
            except Exception as e:
                logger.error(f"failed to install {model_name} ({filename}): {e}")
                ok = False

        return ok    

    def is_installed(self, model_name: str) -> bool:
        model = self.get_model(model_name)
        if not model or not model.get("files"):
            return False

        install_path = model.get("install_path") or ""
        base = Path("/hub/models")

        for file in model["files"]:
            source_path = file.get("path") or ""
            filename = os.path.basename(urlparse(file["source"]).path)
            target_dir = base / install_path / source_path if source_path else base / install_path
            if not (target_dir / filename).exists():
                return False

        return True    