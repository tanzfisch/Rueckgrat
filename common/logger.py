import logging

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

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelname, RESET)
        levelname = record.levelname
        pathname = record.pathname
        lineno = record.lineno
        message = record.getMessage()

        colored_level = f"{color}{levelname}{RESET}:"        
        record.levelname = f"{colored_level:<18}"

        file_line = f"{pathname}:{lineno}"
        record.pathname = f"{file_line}"

        if levelname in ["WARNING", "ERROR", "CRITICAL", "FATAL"]:
            colored_message = f"{color}{message}{RESET}"
        else:
            colored_message = f"{BOLD}{message}{RESET}"
        record.msg = colored_message

        formatted = super().format(record)
        record.levelname = levelname
        record.pathname = pathname
        record.msg = message
        return formatted

class Logger:
    def __init__(self, name=None, level=logging.DEBUG):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        if not self.logger.handlers:
            ch = logging.StreamHandler()
            ch.setLevel(level)
            formatter = ColorFormatter(fmt=f"%(levelname)s %(message)s\n          {DIM}PID:%(process)s %(pathname)s{RESET}")
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)

    def get_logger(self):
        return self.logger
