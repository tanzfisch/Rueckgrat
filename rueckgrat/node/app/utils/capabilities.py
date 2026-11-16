import time
from threading import Lock, Thread
from typing import Any, Callable, Dict, Optional

from app.common import get_logger
logger = get_logger()

RETRY_SECONDS = 300     # a module whose model failed to load is tried again at most this often, when the hub asks


class Modules:
    """the modules of this node by the service type the hub knows them by (text_to_text, text_to_speech, ...).
    None: not installed on this node (its USE_* flag is off). each module tells itself whether it can serve (ready()).
    a failed preload never stops the node: it is logged, the module counts as not loaded and is tried again in the
    background when the hub asks for the report (GET /capabilities), at most every RETRY_SECONDS"""

    def __init__(self):
        self.modules: Dict[str, Optional[Any]] = {}
        self._tried: Dict[str, float] = {}      # service type -> time.monotonic() of its last load attempt
        self._loading: set = set()
        self._lock = Lock()

    def add(self, service: str, factory: Optional[Callable[[], Any]], preload: bool = True) -> Optional[Any]:
        """makes the module of service (factory None: not installed) and loads its model now (preload). returns the module,
        None when it is not installed or could not be made (logged, the node goes on without it)"""
        module = None
        if factory is not None:
            try:
                module = factory()
            except Exception as e:
                logger.error(f"{service} module could not be started, reported as not available: {e!r}")
        self.modules[service] = module
        if module is not None and preload:
            self._preload(service)
        return module

    def get(self, service: str) -> Optional[Any]:
        return self.modules.get(service)

    def _preload(self, service: str) -> bool:
        load = getattr(self.modules.get(service), "preload", None)
        if load is None:
            return True
        self._tried[service] = time.monotonic()
        try:
            load()
            return True
        except Exception as e:
            logger.error(f"{service} module not loaded, reported as not available: {e!r}")
            return False

    def ready(self, service: str) -> bool:
        module = self.modules.get(service)
        if module is None:
            return False
        try:
            return bool(module.ready())
        except Exception as e:
            logger.error(f"{service} readiness check failed: {e!r}")
            return False

    def report(self) -> Dict[str, bool]:
        """service type -> it can serve now. a registered module that is not ready gets another load in the background"""
        report = {service: self.ready(service) for service in self.modules}
        for service, ready in report.items():
            if not ready and self.modules[service] is not None:
                self._retry(service)
        return report

    def _retry(self, service: str):
        with self._lock:
            if service in self._loading or service not in self._tried or time.monotonic() - self._tried[service] < RETRY_SECONDS:
                return
            self._loading.add(service)

        def run():
            try:
                if self._preload(service):
                    logger.info(f"{service} module loaded on retry")
            finally:
                with self._lock:
                    self._loading.discard(service)

        Thread(target=run, name=f"retry-{service}", daemon=True).start()
