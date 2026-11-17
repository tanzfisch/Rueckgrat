"""the queue of the tts node's speech requests: one generation thread speaks them one at a time, a chat's (CHAT) before
the background ones (agent jobs, task and companion passes), first come first served within a priority. a generation
that runs is never interrupted; a waiting request whose client is gone is skipped (SpeechQueue.wait). when MAX_WAITING
requests wait, a new one is refused at once (QueueBusy: the endpoint answers 503 with Retry-After, a background caller
waits and asks again)"""
import asyncio
import heapq
import itertools
import threading
from concurrent.futures import Future, CancelledError
from typing import Awaitable, Callable

from app.common import get_logger
logger = get_logger()

CHAT = "chat"
BACKGROUND = "background"
PRIORITIES = {CHAT: 0, BACKGROUND: 1}   # lower first. an unknown priority (an older hub) counts as a chat's
MAX_WAITING = 64        # requests waiting at once: 8 narrators of a job (one chunk each in flight) and their retries fit many times
DISCONNECT_POLL = 1.0   # seconds between two checks whether the client of a waiting request is still there


class QueueBusy(Exception):
    """MAX_WAITING requests wait already"""


class SpeechQueue:
    def __init__(self, generate: Callable[..., bytes], max_waiting: int = MAX_WAITING):
        """generate(*args) makes one request's speech, only ever called on the queue's thread"""
        self._generate = generate
        self._max_waiting = max_waiting
        self._waiting = []      # heap of (priority rank, arrival number, future, args)
        self._arrivals = itertools.count()
        self._condition = threading.Condition()
        self._thread = None

    def waiting(self) -> int:
        """the requests waiting, the cancelled ones not counted"""
        with self._condition:
            return sum(not item[2].cancelled() for item in self._waiting)

    def submit(self, priority: str, *args) -> Future:
        """queues one request, its future gets the speech (or the generation's exception). QueueBusy when it is full"""
        future = Future()
        with self._condition:
            waiting = sum(not item[2].cancelled() for item in self._waiting)     # a cancelled one is only skipped later
            if waiting >= self._max_waiting:
                raise QueueBusy(f"{waiting} speech requests wait")
            heapq.heappush(self._waiting, (PRIORITIES.get(priority, PRIORITIES[CHAT]), next(self._arrivals), future, args))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="tts-queue")
                self._thread.start()
            self._condition.notify()
        return future

    async def wait(self, future: Future, disconnected: Callable[[], Awaitable[bool]]) -> bytes:
        """the speech of a submitted request, for an async endpoint: while it waits, its client is checked every
        DISCONNECT_POLL seconds, a gone one cancels it (skipped when its turn comes, a running one goes on).
        CancelledError when it was cancelled"""
        wrapped = asyncio.wrap_future(future)
        try:
            while True:
                done, _ = await asyncio.wait({wrapped}, timeout=DISCONNECT_POLL)
                if done:
                    return wrapped.result()
                if await disconnected():
                    if future.cancel():     # False when it runs already: it finishes, no one gets it
                        logger.info("tts: client gone, its waiting request is skipped")
                    raise CancelledError()
        except asyncio.CancelledError:
            future.cancel()     # the endpoint itself was cancelled (the server saw the client go): skipped too
            raise

    def _next(self):
        with self._condition:
            while not self._waiting:
                self._condition.wait()
            return heapq.heappop(self._waiting)[2:]

    def _run(self):
        while True:
            future, args = self._next()
            if not future.set_running_or_notify_cancel():
                continue    # cancelled while it waited
            try:
                future.set_result(self._generate(*args))
            except Exception as e:      # the thread goes on with the next request whatever one does
                future.set_exception(e)
