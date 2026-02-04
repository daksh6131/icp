"""
Logging utilities for ICP Scraper.
"""

import logging
import sys
from config import config


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        # File handler
        if config.LOG_FILE:
            file_handler = logging.FileHandler(config.LOG_FILE)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(console_format)
            logger.addHandler(file_handler)

    return logger
