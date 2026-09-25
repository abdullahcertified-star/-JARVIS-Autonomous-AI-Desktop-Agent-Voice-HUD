"""Structured logging for every request that flows through the dispatcher."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any

import config

_LOGGER_NAME = "jarvis"


def get_logger() -> logging.Logger:
    """Returns the shared JARVIS logger, configuring it on first use."""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        config.LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    console_handler = logging.StreamHandler()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


def log_request(
    action: str,
    target: str | None,
    success: bool,
    message: str,
    duration_ms: float,
) -> None:
    """Logs one structured entry per /execute request."""
    record: dict[str, Any] = {
        "action": action,
        "target": target,
        "success": success,
        "message": message,
        "duration_ms": round(duration_ms, 2),
    }
    logger = get_logger()
    level = logging.INFO if success else logging.WARNING
    logger.log(level, json.dumps(record, ensure_ascii=False))
