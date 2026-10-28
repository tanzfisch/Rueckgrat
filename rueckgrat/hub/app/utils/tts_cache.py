import threading
import time
from collections import OrderedDict


class TtsCache:
    """generated speech wavs, so a replay of a recent message does not call the tts node again.
    keyed by everything the hub sends to the node: (text, voice, language). thread safe"""

    def __init__(self, ttl: float = 3600, max_bytes: int = 100 * 1024 * 1024):
        self.ttl = ttl              # seconds a wav stays usable
        self.max_bytes = max_bytes  # oldest wavs are dropped above this total size
        self._lock = threading.Lock()
        self._entries = OrderedDict()  # key -> (stored_at, wav), oldest first
        self._size = 0

    def get(self, key: tuple) -> bytes | None:
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
            return entry[1] if entry else None

    def put(self, key: tuple, wav: bytes):
        if len(wav) > self.max_bytes:
            return
        with self._lock:
            self._remove(key)
            self._entries[key] = (time.monotonic(), wav)
            self._size += len(wav)
            self._expire()
            while self._size > self.max_bytes:
                self._remove(next(iter(self._entries)))

    def _expire(self):
        now = time.monotonic()
        while self._entries:
            key, (stored_at, _) = next(iter(self._entries.items()))
            if now - stored_at < self.ttl:
                break
            self._remove(key)

    def _remove(self, key: tuple):
        entry = self._entries.pop(key, None)
        if entry:
            self._size -= len(entry[1])
