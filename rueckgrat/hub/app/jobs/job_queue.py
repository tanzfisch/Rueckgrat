from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Optional, List, Dict, Any, Set
from abc import ABC, abstractmethod

from app.common import Logger
logger = Logger(__name__).get_logger()

class Job(ABC):
    def __init__(self):
        self._dependencies: List["Job"] = []
        self._queue: Optional["JobQueue"] = None
        self._done_event = threading.Event()

    def depends_on(self) -> List["Job"]:
        return self._dependencies
    
    def add_dependency(self, dep: "Job"):
        if dep not in self._dependencies:
            self._dependencies.append(dep)

    def create_and_add(self, new_job: "Job"):
        if self._queue is None:
            raise RuntimeError("queue no available")
        self._queue.add(new_job)
        self.add_dependency(new_job)
        logger.debug(f"added new job {type(new_job).__name__}")

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
        self.done_queue: Queue[Job] = Queue()
        self._completed: Set[Job] = set()

        self.executor = ThreadPoolExecutor(max_workers=max_parallel)
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def add(self, job: Job):
        job._queue = self
        self.queue.put(job)

    def _run(self):
        while not self._stop.is_set():
            job = self.queue.get()
            if all(d in self._completed for d in job.depends_on()):  # track completed
                self.executor.submit(self._execute_job, job)
            else:
                self.queue.put(job)  # requeue
            self.queue.task_done()

    def _execute_job(self, job: Job):
        try:
            logger.debug(f"execute {type(job).__name__}")
            job.execute()
            self._completed.add(job)
            self.done_queue.put(job)
        except Exception as e:
            print(f"Job failed ({type(job).__name__}): {e}")
        finally:
            job._done_event.set()

    def get_done(self, timeout: Optional[float] = None) -> Optional[Job]:
        try:
            return self.done_queue.get(timeout=timeout)
        except Empty:
            return None

    def get_done_nowait(self) -> Optional[Job]:
        try:
            return self.done_queue.get_nowait()
        except Empty:
            return None

    def stop(self):
        self._stop.set()
        self.executor.shutdown(wait=True)