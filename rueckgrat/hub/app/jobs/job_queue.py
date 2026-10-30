from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Optional, List, Dict, Any, Set
from abc import ABC, abstractmethod

from app.common import get_logger, current_user_id
logger = get_logger()

class Job(ABC):
    def __init__(self):
        self._dependencies: List["Job"] = []
        self._queue: Optional["JobQueue"] = None
        self._done_event = threading.Event()
        # the user the job works for: its messages and its result go only to this user's websockets.
        # subclasses set it after super().__init__(), sub jobs inherit it from their parent (add_sub_job)
        if not hasattr(self, "user_id"):
            self.user_id: Optional[int] = None

    def depends_on(self) -> List["Job"]:
        return self._dependencies
    
    def add_dependency(self, dep: "Job"):
        if dep not in self._dependencies:
            self._dependencies.append(dep)

    def add_sub_job(self, new_job: "Job"):
        if self._queue is None:
            raise RuntimeError("queue no available")
        if getattr(new_job, "user_id", None) is None:
            new_job.user_id = self.user_id
        self._queue.add(new_job)
        self.add_dependency(new_job)

    def wait_for(self, jobs: List["Job"], timeout: Optional[float] = None) -> bool:
        if not jobs:
            return True
        for job in jobs:
            if not job._done_event.wait(timeout=timeout):
                return False
        return True
    
    def has_response(self) -> bool:
        return False

    @abstractmethod
    def execute(self) -> None: ...

    @abstractmethod
    def result(self) -> Dict[str, Any]: ...

class JobQueue:
    def __init__(self, max_parallel: int = 4):
        self.queue: Queue[Job] = Queue()
        self._done_queues: Dict[int, Queue[Job]] = {}   # user_id -> finished jobs with a response for that user
        self._done_lock = threading.Lock()
        self._completed: Set[Job] = set()

        self.executor = ThreadPoolExecutor(max_workers=max_parallel)
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def add(self, job: Job):
        job._queue = self
        self.queue.put(job)

    def run(self, job: Job) -> bool:
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

    def _done_queue(self, user_id: int) -> "Queue[Job]":
        with self._done_lock:
            return self._done_queues.setdefault(user_id, Queue())

    def _execute_job(self, job: Job):
        # status messages of the job (and the tools it runs) go to its user. a job without a user
        # (run() on the thread of its caller) keeps the caller's user
        token = current_user_id.set(job.user_id) if job.user_id is not None else None
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
            if token is not None:
                current_user_id.reset(token)
            job._done_event.set()

    def get_done(self, user_id: int, timeout: Optional[float] = None) -> Optional[Job]:
        """next finished job with a response for this user"""
        try:
            return self._done_queue(user_id).get(timeout=timeout)
        except Empty:
            return None

    def get_done_nowait(self, user_id: int) -> Optional[Job]:
        try:
            return self._done_queue(user_id).get_nowait()
        except Empty:
            return None

    def stop(self):
        self._stop.set()
        self.executor.shutdown(wait=True)