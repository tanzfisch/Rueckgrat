from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import Optional, List, Dict, Any, Set, Callable
from abc import ABC, abstractmethod

from contextlib import nullcontext
from app.common import get_logger, MessageQueue
logger = get_logger()

class Task(ABC):
    def __init__(self):
        self._dependencies: List["Task"] = []
        self._queue: Optional["TaskQueue"] = None
        self._done_event = threading.Event()
        # the user the job works for: its messages and its result go only to this user's websockets.
        # subclasses set it after super().__init__(), sub jobs inherit it from their parent (add_sub_task)
        if not hasattr(self, "user_id"):
            self.user_id: Optional[int] = None
        self._done_callbacks: List[Callable[["Task"], None]] = []

    def add_done_callback(self, callback: Callable[["Task"], None]) -> None:
        """callback(job) once execute() has returned or raised, on the thread that ran the job, before wait_for returns"""
        self._done_callbacks.append(callback)

    def depends_on(self) -> List["Task"]:
        return self._dependencies
    
    def add_dependency(self, dep: "Task"):
        if dep not in self._dependencies:
            self._dependencies.append(dep)

    def add_sub_task(self, new_job: "Task"):
        if self._queue is None:
            raise RuntimeError("queue no available")
        if getattr(new_job, "user_id", None) is None:
            new_job.user_id = self.user_id
        self._queue.add(new_job)
        self.add_dependency(new_job)

    def wait_for(self, jobs: List["Task"], timeout: Optional[float] = None) -> bool:
        if not jobs:
            return True
        for job in jobs:
            if not job._done_event.wait(timeout=timeout):
                return False
        return True
    
    def has_response(self) -> bool:
        return False

    @abstractmethod
    def get_result(self) -> Dict[str, Any]: ...

    @abstractmethod
    def execute(self) -> None: ...

class TaskQueue:
    def __init__(self, max_parallel: int = 4):
        self.queue: Queue[Task] = Queue()
        self._done_queues: Dict[int, Queue[Task]] = {}   # user_id -> finished jobs with a response for that user
        self._done_lock = threading.Lock()
        self._completed: Set[Task] = set()

        self.executor = ThreadPoolExecutor(max_workers=max_parallel)
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def add(self, job: Task):
        job._queue = self
        self.queue.put(job)

    def run(self, job: Task) -> bool:
        job._queue = self
        try:
            self._execute_job(job)
            return True
        except Exception:
            return False

    def _run(self):
        while not self._stop.is_set():
            job = self.queue.get()
            if all(d in self._completed for d in job.depends_on()):  # track completed
                self.executor.submit(self._execute_job, job)
            else:
                self.queue.put(job)  # requeue
            self.queue.task_done()

    def _done_queue(self, user_id: int) -> "Queue[Task]":
        with self._done_lock:
            return self._done_queues.setdefault(user_id, Queue())

    def _execute_job(self, job: Task):
        # status messages of the job (and the tools it runs) go to its user. a job without a user
        # (run() on the thread of its caller) keeps the caller's user
        scope = MessageQueue.user_scope(job.user_id) if job.user_id is not None else nullcontext()
        try:
            with scope:
                started = time.perf_counter()
                try:
                    logger.debug(f"execute {type(job).__name__}")
                    job.execute()
                    self._completed.add(job)
                    if job.has_response():
                        if job.user_id is None:
                            logger.warning(f"{type(job).__name__} has a response but no user, dropped")
                        else:
                            self._done_queue(job.user_id).put(job)
                except Exception as e:
                    print(f"Job failed ({type(job).__name__}): {e}")
                finally:
                    logger.debug(f"{type(job).__name__} took {time.perf_counter() - started:.2f}s")
                    for callback in getattr(job, "_done_callbacks", ()):
                        try:
                            callback(job)
                        except Exception as e:
                            logger.error(f"done callback of {type(job).__name__} failed {repr(e)}")
        finally:
            job._done_event.set()

    def get_done(self, user_id: int, timeout: Optional[float] = None) -> Optional[Task]:
        """next finished job with a response for this user"""
        try:
            return self._done_queue(user_id).get(timeout=timeout)
        except Empty:
            return None

    def stop(self):
        self._stop.set()
        self.executor.shutdown(wait=True)