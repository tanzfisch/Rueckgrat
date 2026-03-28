import os
import json
import requests
from urllib.parse import urlparse
from pathlib import Path
from tqdm import tqdm

INFRASTRUCTURE_CONFIG_PATH = Path("node/config/infrastructure.json")

class ModelRegistry:

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.registry_file = self.base_dir / "registry.json"
        self._load_registry()
        self._load_infrastructure()        

    def find_valid_url(self, source_url: str, install_path: str, alternative_source: str=None):
        filename = Path(source_url).name
        url = None

        if alternative_source:
            test_url = f"http://{alternative_source}/download/{install_path}/{filename}"
            if self._url_exists(test_url):
                url = test_url

        if not url:
            for server in self.servers:
                test_url = f"http://{server['host']}:{server['port']}/download/{install_path}/{filename}"
                if self._url_exists(test_url):
                    url = test_url

        if not url:
            if self._url_exists(source_url):
                url = source_url

        return url

    def get_urls(self, model_name: str, alternative_source: str=None):
        model_cfg = self.get_model_cfg(model_name)
        if not model_cfg:
            print(f"Error: model \"{model_name}\" not registered")
            return None

        sources=model_cfg["sources"]
        install_path=model_cfg["install_path"]

        result = []

        for source_url in sources:
            url = self.find_valid_url(source_url, install_path, alternative_source)
            if url:
                result.append(url)

        return result


    def install_model(self, model_name: str, alternative_source: str=None, force_install: bool=False):
        model_cfg = self.get_model_cfg(model_name)
        if not model_cfg:
            print(f"Error: model \"{model_name}\" not registered")
            return None

        sources=model_cfg["sources"]
        install_path=model_cfg["install_path"]

        for source_url in sources:
            url = self.find_valid_url(source_url, install_path, alternative_source)

            if not url:
                print(f"Error: can't find download source for {model_name}")
            else:
                self._download_from_url(url, install_path, force_install)

        return model_cfg if self.check_model_files(model_cfg) else None
        
    def get_registry(self):
        return self.registry.copy()

    def _load_infrastructure(self):
        if INFRASTRUCTURE_CONFIG_PATH.exists():
            with open(INFRASTRUCTURE_CONFIG_PATH, "r") as f:
                infrastructure = json.load(f)
        else:
            infrastructure = {}

        if "servers" in infrastructure:
            self.servers = infrastructure["servers"]
        else:
            self.servers = []       

    def _load_registry(self):
        if self.registry_file.exists():
            with open(self.registry_file, "r") as f:
                self.registry = json.load(f)
        else:
            print(f"Error: registry not found at {self.registry_file}")
            self.registry = {}
            self._save_registry()

    def _save_registry(self):
        with open(self.registry_file, "w") as f:
            json.dump(self.registry, f, indent=2)

    def get_model_size(self, model_cfg) -> int:
        result = 0
        for url in model_cfg["sources"]:
            filepath = self.base_dir / model_cfg["install_path"] / os.path.basename(url)
            size = os.path.getsize(filepath)    # bytes
            result += size / (1024 * 1024 * 1024) # GB  

        return result

    def check_model_files(self, model_cfg):
        for url in model_cfg["sources"]:
            filepath = self.base_dir / model_cfg["install_path"] / os.path.basename(url)
            if not os.path.exists(filepath):
                return False
        
        return True

    def get_model_cfg(self, model_source):
        if model_source in self.registry:
            return self.registry[model_source]
        else:
            return None
        
    def _download_from_url(self, url: str, install_path: str, force_download: bool=False):
        target_dir = self.base_dir / install_path
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = os.path.basename(urlparse(url).path)
        target_file = target_dir / filename

        if force_download and os.path.exists(target_file):
            target_file.unlink(missing_ok=True)

        self._download_file(url, target_file, filename)

    def _url_exists(self, url):
        try:
            r = requests.head(url, allow_redirects=True, timeout=5)
            if r.status_code < 400:
                return True
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
                for chunk in r.iter_content(chunk_size=64*1024):
                    if chunk:  # filter out keep-alive chunks
                        f.write(chunk)
                        pbar.update(len(chunk))