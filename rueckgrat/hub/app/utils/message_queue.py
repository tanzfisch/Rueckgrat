from collections import deque
import threading

from app.common import Logger
logger = Logger(__name__).get_logger()

class MessageQueue:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.queue = deque()
                cls._instance.lock = threading.Lock()
        return cls._instance
    
    def set_status(self, status: str):
        with self.lock:
            self.queue.append({
                "status": {
                    "state": status
                }
            })

    def send_status_message(self, message: str):
        with self.lock:
            self.queue.append({
                "status": {
                    "message": message
                }
            })

    def send_data(self, data: dict):
        with self.lock:
            self.queue.append(data)

    def send_url(self, url: str):
        logger.debug(f"sending url {url}")
        with self.lock:
            self.queue.append({
                "status": {
                    "url": url
                }
            })

    def pop_message(self):
        with self.lock:
            return self.queue.popleft() if self.queue else None