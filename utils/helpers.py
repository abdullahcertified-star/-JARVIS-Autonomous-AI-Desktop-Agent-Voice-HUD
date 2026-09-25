"""Small shared helpers used across action modules."""

from __future__ import annotations

from typing import Any


def ok(message: str, **extra: Any) -> dict[str, Any]:
    """Builds a successful /execute response."""
    return {"success": True, "message": message, **extra}


def fail(message: str, **extra: Any) -> dict[str, Any]:
    """Builds a failed /execute response."""
    return {"success": False, "message": message, **extra}


def first_present(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Returns the value of the first key present (and truthy) in data."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default
