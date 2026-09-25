"""clipboard action: copy, paste (read), and clear."""

from __future__ import annotations

from typing import Any

import pyperclip

from dispatcher import register
from utils.helpers import fail, ok


def _copy(data: dict[str, Any]) -> dict[str, Any]:
    text = data.get("text")
    if text is None:
        return fail("clipboard.copy requires 'text'")
    pyperclip.copy(str(text))
    return ok("Copied text to clipboard")


def _paste(_data: dict[str, Any]) -> dict[str, Any]:
    content = pyperclip.paste()
    return ok("Read clipboard contents", content=content)


def _clear(_data: dict[str, Any]) -> dict[str, Any]:
    pyperclip.copy("")
    return ok("Cleared clipboard")


_OPERATIONS = {
    "copy": _copy,
    "paste": _paste,
    "clear": _clear,
}


@register("clipboard")
def clipboard_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown clipboard operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
