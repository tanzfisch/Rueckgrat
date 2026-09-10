import os
import json
import requests
from urllib.parse import urlparse
from pathlib import Path
from tqdm import tqdm

from app.common import get_logger
logger = get_logger()

INFRASTRUCTURE_CONFIG_PATH = Path("/node/config/infrastructure.json")
REEGISTRY_FILE_PATH = Path("/node/data/registry.json")
MODEL_BASE_DIR = Path("/node/models")


class ModelRegistry:

    def __init__(self):
        MODEL_BASE_DIR.mkdir(parents=True, exist_ok=True)
        self._load_registry()
        self._load_infrastructure()

    def get_registry(self):
        return self.registry.copy()

    def get_models(self, type: str = None):
        if not type:
            return list(self.registry.keys())
        return [name for name, cfg in self.registry.items() if cfg.get("type") == type]

    def get_model(self, model_name: str):
        if model_name not in self.registry:
            return None
        return {**self.registry[model_name], "name": model_name}

    def has_model(self, model_name: str) -> bool:
        return model_name in self.registry

    def is_installed(self, model_name: str):
        model = self.get_model(model_name)
        if not model:
            return ""

        files = model["files"]
        install_path = model["install_path"]

        for file in files:
            source_url = file["source"]
            source_path = file["path"]
            local_path = install_path + "/" + source_path if source_path else install_path
            filepath = MODEL_BASE_DIR / local_path / os.path.basename(source_url)
            if not os.path.exists(filepath):
                return False

        return True

    def find_local(self, model_name: str) -> str:
        model = self.get_model(model_name)
        if not model:
            return None
        
        files = model["files"]
        install_path = model["install_path"]
        
        for file in files:
            filename = Path(file["source"]).name
            source_path = file["path"]
            local_path = install_path + "/" + source_path if source_path else install_path
            local_path += "/" + filename

            addr = self._find_local(local_path)
            if addr:
                return addr
        
        return None

    def _find_local(self, local_path: str) -> str:
        for host in self.hosts:
            node = host.get("node") or {}
            addr = host.get("addr")
            port = node.get("port")
            if not addr or port is None:
                continue
            test_url = f"http://{addr}:{port}/downloads/models/{local_path}"
            if self._url_exists(test_url):
                return f"{addr}:{port}"
        
        return None

    def get_description(self, model_name: str) -> str:
        model = self.get_model(model_name)
        if not model:
            return ""
        return model.get("description", "")

    def get_comment(self, model_name: str) -> str:
        model = self.get_model(model_name)
        if not model:
            return ""
        return model.get("comment", "")

    def get_compatibility(self, model_name: str):
        model = self.get_model(model_name)
        if not model:
            return ""
        return model.get("compatibility")

    def get_files(self, model_name: str):
        model = self.get_model(model_name)
        if not model:
            return ""
        return model.get("files")

    def get_install_path(self, model_name: str) -> str:
        model = self.get_model(model_name)
        if not model:
            return ""
        return model.get("install_path", "")

    def get_size(self, model_name: str) -> int:
        if not self.has_model(model_name):
            return 0
        result = 0
        files = self.get_files(model_name)
        install_path = self.get_install_path(model_name)

        for file in files:
            source_url = file["source"]
            source_path = file["path"]
            local_path = install_path + "/" + source_path if source_path else install_path
            filepath = MODEL_BASE_DIR / local_path / os.path.basename(source_url)
            result += os.path.getsize(filepath)

        return result

    def get_safetensors(self, model_name: str) -> Path:
        model = self.get_model(model_name)
        if not model:
            return Path()

        files = model["files"]
        install_path = model["install_path"]

        for file in files:
            source_url = file["source"]
            source_path = file["path"]
            local_path = install_path + "/" + source_path if source_path else install_path
            filepath = MODEL_BASE_DIR / local_path / os.path.basename(source_url)
            if filepath.suffix.lower() == ".safetensors":
                return filepath

        logger.error("model has no safetensors")
        return Path()

    def get_hosts(self):
        return list(self.hosts)

    def get_nodes(self):
        result = []
        for host in self.hosts:
            node = host.get("node")
            if not node:
                continue
            result.append({
                "addr": host.get("addr"),
                "port": node.get("port"),
                "services": node.get("services") or [],
                "modules": node.get("modules") or [],
                "hub": host.get("hub"),
                "chat": host.get("chat"),
            })
        return result

    def is_node_online(self, node) -> bool:
        addr = node.get("addr")
        port = node.get("port")
        if not addr or port is None:
            return False
        return self._url_exists(f"http://{addr}:{port}/health")

    def install_model(self, model_name: str, alternative_server: str = None, force_install: bool = False):
        try:
            model = self.get_model(model_name)
            if not model:
                print(f"Error: model \"{model_name}\" not registered")
                return None

            files = model["files"]
            install_path = model["install_path"]

            for file in files:
                source_url = file["source"]
                source_path = file["path"]
                local_path = install_path + "/" + source_path if source_path else install_path

                url = self._find_valid_url(source_url, local_path, alternative_server)

                if not url:
                    print(f"Error: can't find download source for {model_name}")
                else:
                    self._download_from_url(url, install_path, force_install)

            return model if self.is_installed(model_name) else None

        except Exception as e:
            logger.error(f"failed to install model: {e}")

        return None

    def get_urls(self, model_name: str, alternative_server: str = None):
        try:
            model = self.get_model(model_name)
            if not model:
                print(f"Error: model \"{model_name}\" not registered")
                return None

            files = model["files"]
            install_path = model["install_path"]

            result = []

            for file in files:
                source_url = file["source"]
                source_path = file["path"]
                local_path = install_path + "/" + source_path if source_path else install_path

                url = self._find_valid_url(source_url, local_path, alternative_server)
                if url:
                    result.append(url)

            return result
        except Exception as e:
            logger.error(f"failed to get urls: {e}")

        return None

    def _save_registry(self):
        with open(REEGISTRY_FILE_PATH, "w") as f:
            json.dump(self.registry, f, indent=2)

    def _download_from_url(self, url: str, install_path: str, force_download: bool = False):
        target_dir = MODEL_BASE_DIR / install_path
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = os.path.basename(urlparse(url).path)
        target_file = target_dir / filename

        if force_download and os.path.exists(target_file):
            target_file.unlink(missing_ok=True)

        self._download_file(url, target_file, filename)

    def _url_exists(self, url):
        try:
            r = requests.get(url, stream=True, timeout=5)
            return r.status_code < 400
        except requests.RequestException:
            return False

    def _download_file(self, url: str, filepath: str, download_name: str):
        if os.path.exists(filepath):
            return

        r = requests.get(url, stream=True)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", 0))

        with open(filepath, "wb") as f:
            with tqdm(total=total_size, unit="B", unit_scale=True, desc=f"Downloading {download_name}", unit_divisor=1024) as pbar:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

    def _load_registry(self):
        if REEGISTRY_FILE_PATH.exists():
            with open(REEGISTRY_FILE_PATH, "r") as f:
                self.registry = json.load(f)
        else:
            logger.error(f"registry not found at {REEGISTRY_FILE_PATH}")
            self.registry = {}
            self._save_registry()

    def _load_infrastructure(self):
        if INFRASTRUCTURE_CONFIG_PATH.exists():
            with open(INFRASTRUCTURE_CONFIG_PATH, "r") as f:
                infrastructure = json.load(f)
        else:
            infrastructure = {}

        self.hosts = infrastructure.get("hosts", [])

    def _find_valid_url(self, source_url: str, install_path: str, alternative_server: str = None):
        try:
            filename = Path(source_url).name
            url = None

            if alternative_server:
                test_url = f"http://{alternative_server}/downloads/models/{install_path}/{filename}"
                if self._url_exists(test_url):
                    url = test_url

            if not url:
                for host in self.hosts:
                    node = host.get("node") or {}
                    addr = host.get("addr")
                    port = node.get("port")
                    if not addr or port is None:
                        continue
                    test_url = f"http://{addr}:{port}/downloads/models/{install_path}/{filename}"
                    if self._url_exists(test_url):
                        url = test_url
                        logger.debug(f"{test_url} exists")
                        break

            if not url:
                if self._url_exists(source_url):
                    url = source_url

            return url

        except Exception as e:
            logger.error(f"failed to look for valid url: {e}")

        return None