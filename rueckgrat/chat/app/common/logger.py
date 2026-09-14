import os
import sys
import logging
import threading
import argparse
from pathlib import Path

# ANSI color codes
RESET = "\033[0m"

# Basic colors
BLACK   = "\033[30m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

# Bright versions
BRIGHT_BLACK   = "\033[90m"
BRIGHT_RED     = "\033[91m"
BRIGHT_GREEN   = "\033[92m"
BRIGHT_YELLOW  = "\033[93m"
BRIGHT_BLUE    = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN    = "\033[96m"
BRIGHT_WHITE   = "\033[97m"

# Background colors
BG_BLACK   = "\033[40m"
BG_RED     = "\033[41m"
BG_GREEN   = "\033[42m"
BG_YELLOW  = "\033[43m"
BG_BLUE    = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_CYAN    = "\033[46m"
BG_WHITE   = "\033[47m"

# Bright background
BG_BRIGHT_BLACK   = "\033[100m"
BG_BRIGHT_RED     = "\033[101m"
BG_BRIGHT_GREEN   = "\033[102m"
BG_BRIGHT_YELLOW  = "\033[103m"
BG_BRIGHT_BLUE    = "\033[104m"
BG_BRIGHT_MAGENTA = "\033[105m"
BG_BRIGHT_CYAN    = "\033[106m"
BG_BRIGHT_WHITE   = "\033[107m"

# Text styles
BOLD      = "\033[1m"
DIM       = "\033[2m"
ITALIC    = "\033[3m"
UNDERLINE = "\033[4m"
INVERSE   = "\033[7m"

class ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        "DEBUG": CYAN,
        "INFO": GREEN,
        "WARNING": YELLOW,
        "ERROR": RED,
        "CRITICAL": MAGENTA
    }

    def __init__(self, use_colors=True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_colors = use_colors

    def format(self, record):
        record = logging.makeLogRecord(record.__dict__.copy())
        msg = record.getMessage()
        
        if self.use_colors:
            color = self.LEVEL_COLORS.get(record.levelname, RESET)
            colored_level = f"{color}{record.levelname}{RESET}:"
            if record.levelname in ["WARNING", "ERROR", "CRITICAL", "FATAL"]:
                colored_msg = f"{color}{msg}{RESET}"
            else:
                colored_msg = f"{BOLD}{msg}{RESET}"
        else:
            colored_level = f"{record.levelname}:"
            colored_msg = msg
        
        record.msg = colored_msg
        record.args = ()
        

        if self.use_colors:
            record.levelname = f"{colored_level:<18}"
            record.pathname = f"{DIM}{record.pathname}:{record.lineno}{RESET}"
        else:
            record.levelname = f"{colored_level:<9}"
            record.pathname = f"{record.pathname}:{record.lineno}"
        
        return super().format(record)

class LockedStreamHandler(logging.StreamHandler):
    def __init__(self, lock, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = lock

    def emit(self, record):
        with self._lock:
            super().emit(record)

class HealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.args and len(record.args) >= 3 and record.args[2] == "/health")

class Logger:
    def __init__(self, level=logging.DEBUG):
        if sys.platform != "android":
            parser = argparse.ArgumentParser()
            parser.add_argument("--logfile", default=None)
            args, _ = parser.parse_known_args()
            logfile = args.logfile
        else:
            logfile = None

        self._logger = logging.getLogger("Rückgrat")
        self._logger.setLevel(level)
        self._lock = threading.Lock()

        if not self._logger.handlers:
            if logfile:
                logfile_path = Path(os.path.expanduser(logfile))
                os.makedirs(logfile_path.parent, exist_ok=True)
                fh = logging.FileHandler(logfile_path, mode="w")
                os.chmod(logfile_path, 0o666)
                fh.setLevel(level)
                fh.setFormatter(ColorFormatter(
                    use_colors=False,
                    fmt="%(levelname)s %(message)s\n          %(pathname)s",
                ))
                self._logger.addHandler(fh)
                self._logger.debug(f"logging to file {logfile_path}")

            ch = LockedStreamHandler(self._lock, sys.stderr)
            ch.setLevel(level)
            ch.setFormatter(ColorFormatter(
                use_colors=True,
                fmt="%(levelname)s %(message)s\n          %(pathname)s",
            ))
            self._logger.addHandler(ch)

        access = logging.getLogger("uvicorn.access")
        if not any(isinstance(f, HealthFilter) for f in access.filters):
            access.addFilter(HealthFilter())

    def get_logger(self):
        return self._logger

def get_logger(level=logging.DEBUG):
    return Logger(level).get_logger()