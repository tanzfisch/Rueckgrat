import os
import json
from queue import Queue
import queue
from concurrent.futures import ThreadPoolExecutor
import threading
from tqdm import tqdm
from urllib.parse import urlparse
from pathlib import Path
import requests
import time
from dataclasses import dataclass

from .logger import Logger
logger = Logger(__name__).get_logger()

@dataclass
class DownloadJob:
    def __init__(self, url: str, download_path: str, access_token: str, server_cert: str, max_retry: int = 4, force_download: bool = False):
        self.url = url
        self.download_path = download_path
        self.access_token = access_token
        self.server_cert = server_cert
        self.force_download = force_download
        self.max_retry = max_retry

    def __eq__(self, other):
        if isinstance(other, DownloadJob):
            return (self.url == other.url and
                    self.download_path == other.download_path and
                    self.access_token == other.access_token and
                    self.server_cert == other.server_cert and
                    self.force_download == other.force_download)
        return False

class DownloadQueue:
    def __init__(self, max_parallel: int = 8, delay: int = 10):
        self.delay = delay
        self.queue: Queue[DownloadJob] = Queue()        
        self._queue_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_parallel)
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def add(self, url: str, download_path: str, access_token: str, server_cert: str, max_retry: int = 4, force_download: bool=False):
        job = DownloadJob(
            url=url,
            download_path=download_path,
            access_token=access_token,
            server_cert=server_cert,
            force_download=force_download,
            max_retry = max_retry
        )

        with self._queue_lock:
            for existing_job in list(self.queue.queue):
                if job == existing_job:
                    print("Job already in the queue.")
                    return

            logger.debug(f"adding to download queue {url}")
            self.queue.put(job)

    def stop(self):
        self._stop.set()
        self.executor.shutdown(wait=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                job = self.queue.get(timeout=0.5)
                future = self.executor.submit(self._execute, job)
                future.add_done_callback(lambda f: self.queue.task_done())
            except queue.Empty:
                continue

    def _execute(self, job: DownloadJob):
        try:
            success = False
            for attempt in range(job.max_retry + 1):
                success = self._download(job.url, job.download_path, job.access_token, job.server_cert, job.force_download)
                
                if success:
                    break
                
                if attempt < job.max_retry:
                    time.sleep(self.delay * attempt)
                    logger.debug(f"retry download {job.url}")

            if not success:
                logger.error(f"failed to download {job.url}")
            else:
                logger.info(f"downloaded {job.url}")

        except Exception as e:
            print(f"DownloadJob failed: {e}")

    def _download(self, url: str, download_path: str, access_token: str, server_cert: str, force_download: bool=False) -> bool:
        try:
            target_path = Path(download_path)
            target_path.mkdir(parents=True, exist_ok=True)

            filename = os.path.basename(urlparse(url).path)
            target_filepath = target_path / filename

            if target_filepath.exists() and not force_download:
                return True

            if target_filepath.exists() and force_download:
                target_filepath.unlink(missing_ok=True)

            logger.debug(f"Downloading {url} -> {target_filepath}")
            return self._download_file(url, target_filepath, access_token, server_cert)
        
        except Exception as e:
            logger.error(f"failed to download {url} {repr(e)}")
            return False

    def _download_file(self, url: str, filepath: Path, access_token: str, server_cert: str) -> bool:
        if filepath.exists():
            return True

        response = requests.get(
            url, 
            stream=True,
            headers = {
                "Authorization": f"Bearer {access_token}"
            },             
            verify=server_cert
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                data = response.json()
                if "error" in data:
                    return False
            except ValueError:
                return False

        total_size = int(response.headers.get("content-length", 0))

        with open(filepath, "wb") as file:
            with tqdm(total=total_size, unit="B", unit_scale=True, desc=f"Downloading {url}", unit_divisor=1024) as pbar:
                for chunk in response.iter_content(chunk_size=64*1024):
                    if chunk:
                        file.write(chunk)
                        pbar.update(len(chunk))

        return True
