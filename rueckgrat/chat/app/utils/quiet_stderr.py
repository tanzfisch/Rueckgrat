"""quiet_stderr: hides the lines a C library writes straight to file descriptor 2 (python's sys.stderr redirects can't
catch them), e.g. libmpg123's decode notes inside libsndfile. fd 2 goes to a temporary file for the block only; after it,
fd 2 is restored and every captured line that is not noise is written to it again, so another thread's log output in
that window is only delayed, not lost. one block at a time (fd 2 is the whole process's). without a usable fd 2 (some
GUI or mobile runs) the block just runs"""
import os
import re
import sys
import tempfile
import threading
from contextlib import contextmanager

_lock = threading.Lock()


def _flush() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except Exception:
            pass


@contextmanager
def quiet_stderr(noise: re.Pattern):
    """noise: a bytes pattern, matched at the start of each captured line; matching lines are dropped"""
    with _lock:
        try:
            saved = os.dup(2)
        except OSError:
            saved = None
        if saved is None:
            yield
            return
        with tempfile.TemporaryFile() as sink:
            _flush()
            os.dup2(sink.fileno(), 2)
            try:
                yield
            finally:
                _flush()
                os.dup2(saved, 2)
                os.close(saved)
                sink.seek(0)
                kept = [line for line in sink.read().splitlines(keepends=True) if not noise.match(line)]
                if kept:
                    os.write(2, b"".join(kept))
