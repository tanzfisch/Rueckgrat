"""VoiceConds: chatterbox's prepared conditionals of the reference voices, so a voice wav is not loaded, resampled and
embedded again (prepare_conditionals) for every chunk of a long speech. one entry per voice file, keyed on its path,
mtime and size: a changed file is a miss and replaces its old entry. a small LRU (MAX_VOICES), thread-safe"""
import copy
import os
import threading
from collections import OrderedDict
from typing import Any, Callable

from app.common import get_logger
logger = get_logger()

MAX_VOICES = 8      # a job's narrators and a few contacts; one entry is well under 1 MB on the gpu (embeddings, a 10 s mel prompt)


class VoiceConds:
    def __init__(self, max_voices: int = MAX_VOICES):
        self._max = max_voices
        self._entries: "OrderedDict[str, tuple[tuple[int, int], Any]]" = OrderedDict()    # path -> ((mtime_ns, size), conds)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, path: str, prepare: Callable[[str], Any]) -> Any:
        """a copy of the voice's conditionals, prepare(path) makes them on a miss (it runs under the lock: one voice is
        never prepared twice at once). the copy is shallow: chatterbox's generate replaces conds.t3 for another
        exaggeration but never changes a tensor in place, so the cached entry stays as prepared. OSError when the file
        is gone"""
        stat = os.stat(path)
        version = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            entry = self._entries.get(path)
            if entry is not None and entry[0] == version:
                self._entries.move_to_end(path)
                self._hits += 1
                return copy.copy(entry[1])
            self._misses += 1
            if entry is not None:
                logger.debug(f"voice {path} changed, preparing it again")
            conds = prepare(path)
            self._entries[path] = (version, conds)
            self._entries.move_to_end(path)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
            return copy.copy(conds)

    def clear(self) -> None:
        """the entries belong to one loaded model"""
        with self._lock:
            self._entries.clear()
