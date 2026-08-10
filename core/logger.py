import logging
import sys

# ANSI color codes
RESET   = "\033[0m"
GREY    = "\033[38;5;240m"
CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
MAGENTA = "\033[35m"

LEVEL_COLORS = {
    "DEBUG":    GREY,
    "INFO":     CYAN,
    "WARNING":  YELLOW,
    "ERROR":    RED,
    "CRITICAL": MAGENTA,
}

# Warna per keyword di message
MESSAGE_COLORS = {
    "job_received":   "\033[34m",    # blue
    "job_processing": "\033[36m",    # cyan
    "job_finished":   "\033[32m",    # green
    "job_done":       "\033[38;5;240m",  # grey
    "job_error":      "\033[31m",    # red
    "callback_sent":  "\033[32m",    # green
    "callback_retry": "\033[33m",    # yellow
    "callback_timeout": "\033[33m",  # yellow
    "callback_exhausted": "\033[31m", # red
}


class ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        level_color = LEVEL_COLORS.get(record.levelname, RESET)
        level_str = f"{level_color}{record.levelname:<8}{RESET}"

        # Warna message berdasarkan keyword pertama
        msg = record.getMessage()
        msg_color = RESET
        for keyword, color in MESSAGE_COLORS.items():
            if msg.startswith(keyword):
                msg_color = color
                break

        time_str = f"{GREY}{self.formatTime(record, self.datefmt)}{RESET}"
        name_str = f"{GREY}{record.name}{RESET}"

        return f"{time_str} [{level_str}] {name_str}: {msg_color}{msg}{RESET}"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(ColorFormatter(datefmt="%Y-%m-%d %H:%M:%S"))

    logger.addHandler(handler)
    logger.propagate = False

    return logger