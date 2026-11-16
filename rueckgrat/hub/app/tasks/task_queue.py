from queue import Queue
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import Optional, List, Dict, Any, Set, Callable
from abc import ABC, abstractmethod

from contextlib import nullcontext
from app.common import get_logger, MessageQueue
logger = get_logger()

class Task(ABC):
    def __init__(self, user_id: Optional[int] = None, conversation_id: Optional[int] = None):
        self._dependencies: List["Task"] = []
        self._queue: Optional["TaskQueue"] = None
        self._done_event = threading.Event()
        # where the messages of the job go: the user the job works for (its messages and its result go only to this
        # user's websockets), the websocket session that asked for it while that is open (take_caller_session) and the
        # conversation its status messages carry. sub jobs inherit them from their parent (add_sub_task)
        self._user_id = user_id
        self._session: Optional[int] = None
        self._conversation_id = conversation_id
        self._done_callbacks: List[Callable[["Task"], None]] = []

    def get_user_id(self) -> Optional[int]:
        return self._user_id

    def get_session(self) -> Optional[int]:
        return self._session

    def get_conversation_id(self) -> Optional[int]:
        return self._conversation_id

    def inherit_route(self, parent: "Task"):
        """a sub job of the same user (or of none) takes the parent's user, session and conversation it has none of"""
        if self.get_user_id() not in (None, parent.get_user_id()):
            return
        if self._user_id is None:
            self._user_id = parent.get_user_id()
        if self._session is None:
            self._session = parent.get_session()
        if self.get_conversation_id() is None:
            self._conversation_id = parent.get_conversation_id()

    def take_caller_session(self):
        """a job of the user of the caller's MessageQueue.user_scope (the websocket's receiver) answers that websocket session"""
        if self._session is None and self.get_user_id() is not None and self.get_user_id() == MessageQueue.get_current_user():
            self._session = MessageQueue.get_current_session()

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
        new_job.inherit_route(self)
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
        self._completed: Set[Task] = set()

        self.executor = ThreadPoolExecutor(max_workers=max_parallel)
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def add(self, job: Task):
        job._queue = self
        job.take_caller_session()
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

    def _execute_job(self, job: Task):
        # messages of the job (and the tools it runs) and its result go to its user's session. a job without a user
        # (run() on the thread of its caller) keeps the caller's scope
        scope = (MessageQueue.user_scope(job.get_user_id(), job.get_session(), job.get_conversation_id())
                 if job.get_user_id() is not None else nullcontext())
        try:
            with scope:
                started = time.perf_counter()
                try:
                    logger.debug(f"execute {type(job).__name__}")
                    job.execute()
                    self._completed.add(job)
                    if job.has_response():
                        if job.get_user_id() is None:
                            logger.warning(f"{type(job).__name__} has a response but no user, dropped")
                        else:
                            MessageQueue().send_data(job.get_result())
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

    def stop(self):
        self._stop.set()
        self.executor.shutdown(wait=True)