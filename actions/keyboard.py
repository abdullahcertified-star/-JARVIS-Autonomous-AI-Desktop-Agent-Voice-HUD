"""keyboard action: type text, press a single key, or fire a hotkey combo."""

from __future__ import annotations

from typing import Any

import keyboard as kb

from dispatcher import register
from utils.helpers import fail, ok


def _type(data: dict[str, Any]) -> dict[str, Any]:
    text = data.get("text")
    if not text:
        return fail("keyboard.type requires 'text'")
    kb.write(str(text))
    return ok(f"Typed {len(text)} character(s)")


def _press(data: dict[str, Any]) -> dict[str, Any]:
    key = data.get("key")
    if not key:
        return fail("keyboard.press requires 'key'")
    kb.press_and_release(str(key))
    return ok(f"Pressed '{key}'")


def _hotkey(data: dict[str, Any]) -> dict[str, Any]:
    keys = data.get("keys")
    if not keys or not isinstance(keys, list):
        return fail("keyboard.hotkey requires 'keys' as a list, e.g. [\"ctrl\", \"c\"]")
    combo = "+".join(str(k) for k in keys)
    kb.press_and_release(combo)
    return ok(f"Sent hotkey {combo}")


_OPERATIONS = {
    "type": _type,
    "press": _press,
    "hotkey": _hotkey,
}


@register("keyboard")
def keyboard_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown keyboard operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
