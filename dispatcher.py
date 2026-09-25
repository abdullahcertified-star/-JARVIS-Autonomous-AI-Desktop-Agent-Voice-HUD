"""Routes validated /execute requests to the registered action handler.

Action modules register themselves with @register("action_name") and are
never imported directly by app.py -- this is the only file that needs to
know an action module exists, and the only file action modules must not
import from (avoids a circular import).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from utils.helpers import fail
from utils.logger import log_request
from utils.validator import validate_request

ActionHandler = Callable[[dict[str, Any]], dict[str, Any]]

_REGISTRY: dict[str, ActionHandler] = {}


def register(name: str) -> Callable[[ActionHandler], ActionHandler]:
    """Decorator: registers a handler function under an action name."""

    def decorator(handler: ActionHandler) -> ActionHandler:
        _REGISTRY[name] = handler
        return handler

    return decorator


def dispatch(data: dict[str, Any]) -> dict[str, Any]:
    """Validates and executes a single /execute request."""
    started = time.perf_counter()

    is_valid, error = validate_request(data)
    if not is_valid:
        result = fail(error or "Invalid request")
        _record(data, result, started)
        return result

    action = data["action"]
    handler = _REGISTRY[action]

    try:
        result = handler(data)
    except Exception as exc:  # noqa: BLE001 - never let a handler crash the server
        result = fail(f"Unhandled error in '{action}': {exc}")

    _record(data, result, started)
    return result


def _record(data: dict[str, Any], result: dict[str, Any], started: float) -> None:
    action = data.get("action") if isinstance(data, dict) else None
    if action == "system" and data.get("operation") == "status":
        return
    duration_ms = (time.perf_counter() - started) * 1000
    target = data.get("target") if isinstance(data, dict) else None
    log_request(
        action=action or "unknown",
        target=target,
        success=bool(result.get("success")),
        message=str(result.get("message", "")),
        duration_ms=duration_ms,
    )


# Imported for their @register side effects only -- must stay at the bottom
# so `register` is already defined when each action module runs.
from actions import (  # noqa: E402,F401
    apps,
    browser,
    clipboard,
    command,
    explorer,
    keyboard,
    media,
    mouse,
    news,
    ocr,
    screenshot,
    system,
)
