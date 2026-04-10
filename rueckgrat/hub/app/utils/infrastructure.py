
import json
import os
import requests

from tqdm import tqdm
from urllib.parse import urlparse
from requests.models import Response
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from ..jobs.image_job import ImageRequest

from app.common import Logger, ChatRequestLlama
logger = Logger(__name__).get_logger()

INFRASTRUCTURE_CONFIG_PATH = Path("/hub/config/infrastructure.json")

def make_error_response(message: str, status_code: int = 500, content_type: str = "application/json") -> Response:
    response = Response()
    response.status_code = status_code

    # Support JSON-style error payloads
    if content_type == "application/json":
        response._content = json.dumps({
            "error": message
        }).encode("utf-8")
    else:
        response._content = message.encode("utf-8")

    response.headers["Content-Type"] = content_type
    return response

@dataclass
class ServerResult:
    url: str
    ok: bool
    error: Optional[str] = None

@dataclass
class StatusResult:
    def __init__(self, servers: list[ServerResult] = None):
        self.servers = servers if servers else []

    servers : list[ServerResult]

class Infrastructure:
    def __init__(self):
        if not INFRASTRUCTURE_CONFIG_PATH.exists():
            logger.error(f"no infrastructure config found at {INFRASTRUCTURE_CONFIG_PATH}")
            return

        with open(INFRASTRUCTURE_CONFIG_PATH, "r") as f:
            data = json.load(f)

        self.servers = data["servers"]

        self.node_with_text_to_text = None
        self.node_with_text_to_image = None
        self.node_with_model_storage = None # TODO

        for server in self.servers:
            if "services" in server:
                services = server["services"]
                for service in services:
                    if service["type"] == "text_to_text":
                        self.node_with_text_to_text = server

                    if service["type"] == "text_to_image":
                        self.node_with_text_to_image = server

        if not self.node_with_text_to_text:
            logger.error("couldn't find text_to_text generator in config")
        else:
            logger.info(f"found text_to_text generator at {self.node_with_text_to_text['host']}:{self.node_with_text_to_text['port']}")

        if not self.node_with_text_to_image:
            logger.warning("couldn't find text_to_image generator in config")
        else:
            logger.info(f"found text_to_image generator at {self.node_with_text_to_image['host']}:{self.node_with_text_to_image['port']}")

    def get_status(self) -> StatusResult:
        result = StatusResult()

        for server in self.servers:             
            url = f"http://{server['host']}:{server['port']}/health"

            try:
                response = requests.get(url, timeout=3)

                ok = response.status_code == 200 \
                and response.json() == {"status": "ok"} \
                and response.headers.get("content-type", "").startswith("application/json")

                if ok:
                    result.servers.append(ServerResult(url, ok))
                else:
                    result.servers.append(ServerResult(url, ok, error=response["status"]))
                                
            except Exception as e:
                result.servers.append(ServerResult(url, False, error=repr(e)))

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

    def _download_from_url(self, url: str, dst_path: str, force_download: bool=False) -> int:
        logger.debug(f"download {url} -> {dst_path}")

        target_path = Path("/node") / dst_path
        target_path.mkdir(parents=True, exist_ok=True)

        filename = os.path.basename(urlparse(url).path)
        target_filepath = target_path / filename

        if os.path.exists(target_filepath):
            target_filepath.unlink(missing_ok=True)

        return self._download_file(url, target_filepath)

    def image(self, image_request: ImageRequest) -> tuple[str, int]:
        if not self.node_with_text_to_image:
            logger.error("no text to image generator available")
            return None

        url_download = f"http://{self.node_with_text_to_image['host']}:{self.node_with_text_to_image['port']}/download"
        url_image_request = f"http://{self.node_with_text_to_image['host']}:{self.node_with_text_to_image['port']}/image"

        try:
            response = requests.post(
                url_image_request,
                json=image_request.model_dump(),
                timeout=60,
            )
        
            if response.status_code == 200:
                data = response.json()
                filepath = Path(data.get("output", []))
            else:
                logger.error(f"failed image request: {response.status_code} {response.reason}")
                return None

        except Exception as e:
            logger.error(f"failed to get a image response {repr(e)}")
            return None

        size = self._download_from_url(f"{url_download}/images/{filepath}", f"/hub/images")

        return str(filepath), size

    def chat(self, messages, temperature: float, low_accuracy: bool = False) -> str:
        url = f"http://{self.node_with_text_to_text['host']}:{self.node_with_text_to_text['port']}/chat"
        
        payload= ChatRequestLlama(
            messages=messages, 
            temperature=temperature, 
            low_accuracy=low_accuracy
        )

        try:
            response = requests.post(
                url,
                json=payload.model_dump(),
                timeout=60,
            )
        
            if response.status_code == 200:
                data = response.json()
                return data.get("content", [])

        except Exception as e:
            logger.error(f"failed to get a chat response {repr(e)}")

        return None

    def get_model_url(self, model_name) -> Response:
        url = f"http://{self.node_with_text_to_text['host']}:{self.node_with_text_to_text['port']}/model"
        
        try:
            response = requests.get(
                url,
                json={"model_name": model_name},
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