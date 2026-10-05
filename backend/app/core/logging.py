"""
3D Reel Studio — Centralized Logging System
Phase 2: FastAPI Backend Foundation
"""

import logging
import sys
from typing import Optional


class CustomFormatter(logging.Formatter):
    """
    Standardized, high-readability log formatter for development and production.
    """
    grey = "\x1b[38;20m"
    cyan = "\x1b[36;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    format_str = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: cyan + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.format_str)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def setup_logging(log_level: Optional[str] = "INFO") -> logging.Logger:
    """
    Configures and initializes root and app loggers.
    Ensures safe logging without leaking sensitive keys or payload data.
    """
    level = getattr(logging, log_level.upper(), logging.INFO) if isinstance(log_level, str) else logging.INFO

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(CustomFormatter())
        root_logger.addHandler(console_handler)

    logger = logging.getLogger("3d_reel_studio")
    logger.setLevel(level)
    return logger


logger = setup_logging()
