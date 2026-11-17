
import asyncio
import base64
import json
import os
import requests
import threading
import time
import uuid
from tqdm import tqdm
from urllib.parse import urlparse
from requests.models import Response
from pathlib import Path
from typing import Optional, Dict, Callable
from dataclasses import dataclass
from ..tasks.image_task import ImageRequest
from .tts_cache import TtsCache

from app.common import get_logger, ChatRequestLlama, DownloadQueue, WebSocketClient
logger = get_logger()

INFRASTRUCTURE_CONFIG_PATH = Path("/hub/config/infrastructure.json")
LONG_REPLY_SHARE = 0.5          # of a llama slot's context for a long reply (tool setup, code, job), the rest is the prompt
MIN_LONG_REPLY_TOKENS = 4096    # also when the context is unknown
DECIDE_BATCH = 64               # questions per /decide request, the node's MAX_DECIDE_QUESTIONS
HUB_IMAGE_DIR = Path("/hub/images")

# capabilities: what the system can do right now, by the names the hub and the app use -> the node service type of each
CAPABILITY_SERVICES = {
    "llm": "text_to_text",
    "tts": "text_to_speech",
    "stt": "speech_to_text",
    "image": "text_to_image",
    "decision": "text_to_decision",
    "embedding": "text_to_embedding",
}
INTERNET = "internet"               # the capability of the tools that fetch from the web, the hub probes it
CAPABILITY_TICK_SECONDS = 2         # how often the watcher looks at the node connections, a (re)connect asks the node right away
CAPABILITY_REFRESH_SECONDS = 30     # a connected node is asked for its loaded modules this often
CAPABILITY_TIMEOUT = 5              # seconds for a node's /capabilities
INTERNET_PROBE_SECONDS = 60
INTERNET_PROBE_TIMEOUT = 3
INTERNET_PROBE_URLS = ("https://1.1.1.1", "https://www.google.com/generate_204")     # any answer of one of them: online

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
        # the node's GET /capabilities: service type -> its module is loaded. None: not asked yet or an older node
        # without it, then its configured services count as loaded
        self.services: Optional[dict[str, bool]] = None

    def fetch_services(self) -> None:
        """asks the node which of its modules can serve now. the node does not know the hub, the hub asks.
        not reachable or an error: the last answer stays, the websocket tells whether the node is there"""
        try:
            response = requests.get(f"http://{self.addr}:{self.port}/capabilities", timeout=CAPABILITY_TIMEOUT)
            if response.status_code == 404:
                self.services = None    # an older node
            elif response.status_code == 200:
                self.services = {str(k): bool(v) for k, v in (response.json().get("services") or {}).items()}
            else:
                logger.warning(f"capabilities of node {self.uri}: {response.status_code} {response.reason}")
        except Exception as e:
            logger.debug(f"capabilities of node {self.uri} not fetched {repr(e)}")

    def has(self, service_type: str) -> bool:
        """the node's module of service_type is loaded, by its last answer"""
        return self.services is None or self.services.get(service_type, False)

class Infrastructure:
    callback_handlers: Dict[str, tuple[int, Callable[[str], None]]] = {}
    _tts_cache = TtsCache()  # generated speech, 1 h, max 100 MB
    # class defaults, so an instance without __init__ (laya_tune: Infrastructure.__new__ and node_by_type for decide) works too
    internet: Optional[bool] = None     # the last internet probe, None: not probed yet (counts as online)
    _live = False                       # connected to the nodes' websockets and watching their capabilities

    @staticmethod
    def slot_context() -> Optional[int]:
        """the context of one llama-server slot: LLAMA_SERVER_MAX_CONTEXT / LLAMA_SERVER_N_PARALLEL, the values compose
        starts the llama server with (.env). None when they are not set"""
        try:
            context = int(os.getenv("LLAMA_SERVER_MAX_CONTEXT") or 0)
            parallel = max(1, int(os.getenv("LLAMA_SERVER_N_PARALLEL") or 1))
        except ValueError:
            return None
        return context // parallel if context > 0 else None

    @classmethod
    def long_reply_tokens(cls) -> int:
        """max_new_tokens of a long reply (a tool setup writing files, a program, an agent job's step): LONG_REPLY_SHARE
        of a slot's context, so it grows with the hardware the llm is started with. at least MIN_LONG_REPLY_TOKENS"""
        slot = cls.slot_context()
        return max(MIN_LONG_REPLY_TOKENS, int(slot * LONG_REPLY_SHARE)) if slot else MIN_LONG_REPLY_TOKENS

    def __init__(self):
        self.node_by_type: dict[str, WebSocketClientNode] = {}
        self.nodes: list[WebSocketClientNode] = []
        self._capability_state: dict = {}
        self._watch_stop = threading.Event()
        logger.info(f"llm slot context {self.slot_context() or 'unknown'}, long replies {self.long_reply_tokens()} tokens")
        if not INFRASTRUCTURE_CONFIG_PATH.exists():
            logger.error(f"no infrastructure config found at {INFRASTRUCTURE_CONFIG_PATH}")
            return

        with open(INFRASTRUCTURE_CONFIG_PATH, "r") as f:
            data = json.load(f)

        self.hosts = data["hosts"]
        self.nodes: list[WebSocketClientNode] = []
        self.node_by_type: dict[str, WebSocketClientNode] = {}

        self.download_queue = DownloadQueue()

    async def connect_nodes(self, connect: bool = True):
        """connect=False: only looks up the nodes, for the http calls (chat without streaming, embed), e.g. hub management"""
        for host in self.hosts:
            if "node" in host:
                node = host["node"]
                websocket_node = WebSocketClientNode(host["addr"], node["port"])
                self.nodes.append(websocket_node)
                # non-blocking: connects whenever the node comes up, reconnects if it restarts
                if connect:
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

        if not "text_to_speech" in self.node_by_type:
            logger.warning("couldn't find text_to_speech generator")

        if not "speech_to_text" in self.node_by_type:
            logger.warning("couldn't find speech_to_text recognizer")

        if not "text_to_embedding" in self.node_by_type:
            logger.warning("couldn't find text_to_embedding service, no memory vectors and no memory search")

        if not "text_to_decision" in self.node_by_type:
            logger.info("couldn't find text_to_decision service, no laya decisions")

        if connect:
            self._live = True
            threading.Thread(target=self._watch_capabilities, name="capabilities", daemon=True).start()

    ########### capabilities: which optional parts are there right now. only the llm is mandatory
    def available(self, name: str) -> bool:
        """capability name (CAPABILITY_SERVICES or INTERNET) can be used now: its service is configured, its node connected and
        the module loaded there (the node's last /capabilities). hub management (connect_nodes(connect=False)) has no websockets
        and does not watch: configured is enough there"""
        if name == INTERNET:
            return self.internet is not False
        service_type = CAPABILITY_SERVICES.get(name)
        node = self.node_by_type.get(service_type) if service_type else None
        if node is None:
            return False
        if not self._live:
            return True
        return node.is_connected() and node.has(service_type)

    def capabilities(self) -> dict[str, bool]:
        """every capability -> available(), for the hub's /capabilities and /health"""
        return {name: self.available(name) for name in [*CAPABILITY_SERVICES, INTERNET]}

    def expected(self) -> list[str]:
        """the capabilities this system is set up for: its service is configured in infrastructure.json, the internet always.
        one of them not available is missing (the app shows it), one not configured is simply not installed"""
        return [name for name, service_type in CAPABILITY_SERVICES.items() if service_type in self.node_by_type] + [INTERNET]

    async def wait_available(self, name: str, seconds: float) -> bool:
        """available(name), waiting up to seconds for it (a node that is reconnecting). False when it is not there by then"""
        deadline = time.monotonic() + seconds
        while not self.available(name):
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.5)
        return True

    def probe_internet(self) -> bool:
        """online when one of INTERNET_PROBE_URLS answers at all, sets self.internet"""
        for url in INTERNET_PROBE_URLS:
            try:
                requests.head(url, timeout=INTERNET_PROBE_TIMEOUT, allow_redirects=False)
                self.internet = True
                return True
            except requests.exceptions.RequestException:
                continue
        self.internet = False
        return False

    def _watch_capabilities(self):
        """asks a node for its loaded modules when it connects or reconnects and every CAPABILITY_REFRESH_SECONDS while it is
        connected, probes the internet every INTERNET_PROBE_SECONDS. a change is logged"""
        connected: dict[WebSocketClientNode, bool] = {}
        asked: dict[WebSocketClientNode, float] = {}
        probed = None
        while True:
            try:
                now = time.monotonic()
                for node in self.nodes:
                    up = node.is_connected()
                    if up and (not connected.get(node) or now - asked.get(node, 0.0) >= CAPABILITY_REFRESH_SECONDS):
                        node.fetch_services()
                        asked[node] = now
                    connected[node] = up
                if probed is None or now - probed >= INTERNET_PROBE_SECONDS:
                    self.probe_internet()
                    probed = now
                self._log_capabilities()
            except Exception as e:
                logger.error(f"capability watcher {repr(e)}")
            if self._watch_stop.wait(CAPABILITY_TICK_SECONDS):
                return

    def _log_capabilities(self):
        state = self.capabilities()
        if state != self._capability_state:
            missing = [name for name, ok in state.items() if not ok]
            logger.info(f"capabilities changed, not available: {', '.join(missing) or 'none'}")
            self._capability_state = state

    def get_status(self) -> StatusResult:
        # the websocket supervisor already tracks every node, no need to poll them over http
        return StatusResult([
            ServerResult(node.uri, node.is_connected(), None if node.is_connected() else "not connected")
            for node in self.nodes
        ])

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

    def _image_payload(self, image_request: ImageRequest) -> dict:
        """the json the node gets. a request with a face reference (reference_image_key) also gets the bytes of that
        hub image, the node can't read /hub/images. without a reference this is exactly model_dump() as before"""
        payload = image_request.model_dump()
        key = image_request.reference_image_key
        if not key:
            return payload

        b64 = image_request.reference_image_b64
        if not b64:
            path = (HUB_IMAGE_DIR / key).resolve()
            if "/" in key or "\\" in key or key.startswith(".") or path.parent != HUB_IMAGE_DIR.resolve():
                logger.warning(f"invalid reference image key {key!r}, generating without face reference")
                return payload
            try:
                b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            except OSError as e:
                # the node falls back to plain generation when it gets a key without bytes
                logger.warning(f"reference image {key} not readable ({e!r}), generating without face reference")
                return payload

        payload["reference_image_b64"] = b64
        return payload

    def image(self, image_request: ImageRequest) -> str:
        if not self.available("image"):
            logger.error("no text to image generator available")
            return None
        
        node = self.node_by_type["text_to_image"]
        url_image_request = f"http://{node.addr}:{node.port}/image"

        try:
            response = requests.post(
                url_image_request,
                json=self._image_payload(image_request),
                timeout=480,
            )
        
            if response.status_code == 200:
                data = response.json()
                filepath = Path(data.get("output") or "")
                if not data.get("output"):
                    logger.error("got invalid file path from image response")
                    return None
            else:
                logger.error(f"failed image request: {response.status_code} {response.reason}")
                return None

        except Exception as e:
            logger.error(f"failed to get a image response {repr(e)}")
            return None        

        return str(filepath)

    def tts(self, text: str, voice: str = "", language: str = "") -> Optional[bytes]:
        """forward a speech request to the tts node, returns wav bytes or None. language "" = the node detects it.
        the wav is cached for an hour, so replaying a recent message does not generate it again"""
        key = (text, voice, language)
        if (wav := self._tts_cache.get(key)) is not None:
            logger.debug("tts: using cached wav")
            return wav
        if not self.available("tts"):
            logger.error("no text to speech generator available")
            return None

        node = self.node_by_type["text_to_speech"]
        base = f"http://{node.addr}:{node.port}"
        if voice and not self._push_voice(base, voice):
            logger.warning(f"voice {voice} not available on the tts node, using default voice")
        url = f"{base}/tts"
        try:
            response = requests.post(url, json={"text": text, "voice": voice, "language": language}, timeout=240)
            if response.status_code != 200:
                logger.error(f"failed tts request: {response.status_code} {response.reason}")
                return None
            self._tts_cache.put(key, response.content)
            return response.content
        except Exception as e:
            logger.error(f"failed to get a tts response {repr(e)}")
            return None

    def stt(self, pcm16: bytes, kind: str, language: str = "") -> Optional[str]:
        """forward 16 kHz mono pcm_s16le audio to the stt node, returns the text or None.
        kind: final (accurate model) or partial (fast model). language "" = whisper detects it"""
        if not self.available("stt"):
            logger.error("no speech to text recognizer available")
            return None

        node = self.node_by_type["speech_to_text"]
        url = f"http://{node.addr}:{node.port}/stt"
        try:
            response = requests.post(
                url,
                params={"kind": kind, "language": language},
                data=pcm16,
                headers={"Content-Type": "application/octet-stream"},
                timeout=120,
            )
            if response.status_code != 200:
                logger.error(f"failed stt request: {response.status_code} {response.reason}")
                return None
            return response.json().get("text", "")
        except Exception as e:
            logger.error(f"failed to get a stt response {repr(e)}")
            return None

    def embed(self, texts: list[str], query: bool = False) -> Optional[list[list[float]]]:
        """text embeddings from the embedding node, one vector per text, or None.
        query: True for search queries, False for texts that are stored"""
        if not self.available("embedding"):
            return None    # not configured: warned once at startup, down: the capability watcher logs it

        node = self.node_by_type["text_to_embedding"]
        url = f"http://{node.addr}:{node.port}/embed"
        try:
            response = requests.post(url, json={"texts": texts, "query": query}, timeout=30)
            if response.status_code != 200:
                logger.error(f"failed embed request: {response.status_code} {response.reason}")
                return None
            return response.json().get("vectors")
        except Exception as e:
            logger.error(f"failed to get an embed response {repr(e)}")
            return None

    def decide(self, state: str, questions: dict) -> Optional[dict]:
        """laya typed decisions about state from the decision node, one forward pass per DECIDE_BATCH questions.
        questions: {id: {"type": "choice"|"score"|"noul", "instructions": ..., "criteria": ...}}
        returns the answers by id (noul: {"noul": P(true), ...}, choice: {"choice": label, ...}) or None when any batch failed"""
        if not self.available("decision"):
            return None     # the callers go on without laya (tool detection: the regex and prompt tools, memory: all candidates)

        items = list(questions.items())
        answers = {}
        for start in range(0, len(items), DECIDE_BATCH):
            batch = self._decide_batch(state, dict(items[start:start + DECIDE_BATCH]))
            if batch is None:
                return None
            answers.update(batch)
        return answers

    def _decide_batch(self, state: str, questions: dict) -> Optional[dict]:
        """one /decide request, at most DECIDE_BATCH questions (the node's limit)"""
        node = self.node_by_type["text_to_decision"]
        url = f"http://{node.addr}:{node.port}/decide"
        try:
            response = requests.post(url, json={"state": state, "questions": questions}, timeout=30)
            if response.status_code != 200:
                logger.error(f"failed decide request: {response.status_code} {response.reason}")
                return None
            return response.json().get("answers")
        except Exception as e:
            logger.error(f"failed to get a decide response {repr(e)}")
            return None

    def drop_voice(self, voice: str) -> bool:
        """removes a cached voice from the tts node after it was deleted on the hub. best effort"""
        if not "text_to_speech" in self.node_by_type:
            return False  # no tts node right now, nothing to clean up
        node = self.node_by_type["text_to_speech"]
        try:
            response = requests.delete(f"http://{node.addr}:{node.port}/voices/{voice}", timeout=10)
            if response.status_code != 200:
                logger.warning(f"failed dropping voice {voice} on tts node: {response.status_code} {response.reason}")
                return False
            return True
        except Exception as e:
            logger.warning(f"failed dropping voice {voice} on tts node {repr(e)}")
            return False

    @staticmethod
    def _push_voice(base: str, voice: str) -> bool:
        """makes sure the node has the voice wav. hub to node only, the node never calls back"""
        path = Path("/hub/voices") / f"{voice}.wav"
        if not path.exists():
            return False  # not a hub stored voice, the node decides what to do with it
        try:
            if requests.head(f"{base}/voices/{voice}", timeout=10).status_code == 200:
                return True  # already cached on the node
            response = requests.put(
                f"{base}/voices/{voice}",
                data=path.read_bytes(),
                headers={"Content-Type": "audio/wav"},
                timeout=60,
            )
            if response.status_code != 200:
                logger.error(f"failed pushing voice {voice}: {response.status_code} {response.reason}")
                return False
            logger.debug(f"pushed voice {voice} to tts node")
            return True
        except Exception as e:
            logger.error(f"failed pushing voice {voice} {repr(e)}")
            return False

    @staticmethod
    def _error_response(conversation_id: int, stream_id: str, error: str) -> str:
        return json.dumps({"conversation_id": conversation_id, "stream_id": stream_id, "response": "", "error": error})

    def _fail_pending_streams(self):
        """connection to the node dropped: in-flight streams will never finish, fail them now"""
        pending = list(self.callback_handlers.items())
        self.callback_handlers.clear()
        for stream_id, (conversation_id, callback) in pending:
            logger.error(f"connection lost during stream for conversation {conversation_id}")
            try:
                callback(self._error_response(conversation_id, stream_id, "connection to node lost"))
            except Exception as e:
                logger.error(f"failed to notify conversation {conversation_id}: {e!r}")

    def _on_incomming_message(self, message: str):
        try:
            data = json.loads(message)
            stream_id = data.get("stream_id")

            handler = self.callback_handlers.get(stream_id)  # gone once cancelled
            if handler:
                handler[1](message)
                if "response" in data:
                    self.callback_handlers.pop(stream_id, None)

        except Exception as e:
            logger.error(f"failed to handle incomming message from node {repr(e)}")

    def cancel(self, stream_id: str):
        """stops a stream: its late deltas are dropped here and the node stops generating"""
        if not stream_id or self.callback_handlers.pop(stream_id, None) is None:
            return
        node = self.node_by_type.get("text_to_text")
        if node and node.is_connected():
            node.send_message(json.dumps({"cancel": stream_id}))

    def chat(self, messages: list, temperature: float, seed: int, conversation_id: int = -1, stream: bool = False, callback = None, max_new_tokens: int = 1024, context_size: int=8192, timeout: Optional[float] = None, json_schema: Optional[dict] = None, info: Optional[dict] = None) -> str:
        try:
            chat_request = ChatRequestLlama(
                messages=messages,
                temperature=temperature,
                seed=seed,
                max_new_tokens=max_new_tokens,
                context_size=context_size,
                stream=stream,
                conversation_id=conversation_id,
                stream_id=uuid.uuid4().hex if stream else None,  # own routing key per stream
                timeout=timeout,
                json_schema=json_schema
            )

            #logger.debug(f"sending query to llm:\n{Utils.pretty_print(chat_request.model_dump())}")

            node = self.node_by_type["text_to_text"]

            if stream:
                if not callback:
                    logger.error(f"need callback for streaming")
                    return None
                
                if not node.is_connected():
                    logger.error(f"node {node.uri} not connected, failing chat request")
                    callback(self._error_response(conversation_id, chat_request.stream_id, "node not connected"))
                    return None

                self.callback_handlers[chat_request.stream_id] = (conversation_id, callback)
                payload = {"chat": chat_request.model_dump()}
                node.send_message(json.dumps(payload))
                return chat_request.stream_id
            else:
                url = f"http://{node.addr}:{node.port}/chat"
                response = requests.post(
                    url,
                    json=chat_request.model_dump(),
                    timeout=240 if timeout is None else timeout + 15,     # the node times out first and says so
                )
            
                if response.status_code == 200:
                    data = response.json()
                    if data.get("role") == "error":     # the node's llama call failed, content is the error, not a reply
                        logger.error(f"chat failed on the node: {data.get('content')}")
                        return None
                    if info is not None:    # an older node sends none of them
                        info.update({key: data[key] for key in ("finish_reason", "prompt_tokens", "completion_tokens") if data.get(key)})
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