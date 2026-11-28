"""
stderr progress for a laya_tune run: the start and end of a phase, and one line per row with the rate and ETA.
stdout stays the tables. Python is run unbuffered (tune.sh: -u, PYTHONUNBUFFERED=1) so the lines show live.
"""
import sys
import time
from typing import Callable, Optional


def duration(seconds: float) -> str:
    """a short clock: 12s, 3m 2s, 3h 2m"""
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def rate_and_eta(elapsed: float, done: int, total: int) -> str:
    """'22.6s/row ETA 3h 2m', or 'ETA —' before the first row finishes"""
    if done <= 0:
        return "ETA —"
    per = elapsed / done
    return f"{per:.1f}s/row ETA {duration(per * max(0, total - done))}"


def short_label(text: str, length: int = 40) -> str:
    """one line, cut after length"""
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[: length - 3] + "..."


def progress_line(done: int, total: int, elapsed: float, label: str = "", outcome: str = "") -> str:
    """[12/539] 22.6s/row ETA 3h 2m  What's the capital of Australia  websearch=0.21"""
    line = f"[{done}/{total}] {rate_and_eta(elapsed, done, total)}"
    if label:
        line += f"  {label}"
    if outcome:
        line += f"  {outcome}"
    return line


def emit(message: str) -> None:
    """one progress line, flushed to stderr so a table on stdout does not hide it"""
    print(message, file=sys.stderr, flush=True)


class Progress:
    """start/done of a scoring phase, and a line for each row"""

    def __init__(self, write: Optional[Callable[[str], None]] = None):
        self._write = write or emit
        self._title = ""
        self._started = 0.0

    def start(self, title: str) -> None:
        self._title = title
        self._started = time.monotonic()
        self._write(title)

    def row(self, done: int, total: int, label: str = "", outcome: str = "", elapsed: Optional[float] = None) -> None:
        if elapsed is None:
            elapsed = time.monotonic() - self._started if self._started else 0.0
        self._write(progress_line(done, total, elapsed, label, outcome))

    def done(self, detail: str = "") -> None:
        elapsed = time.monotonic() - self._started if self._started else 0.0
        suffix = f"  {detail}" if detail else ""
        self._write(f"done {self._title}  {elapsed:.1f}s{suffix}")
