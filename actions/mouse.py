"""mouse action: move, click, double-click, drag, scroll, and query position."""

from __future__ import annotations

from typing import Any

import mouse as ms

from dispatcher import register
from utils.helpers import fail, ok

_VALID_BUTTONS = {"left", "right", "middle"}


def _move(data: dict[str, Any]) -> dict[str, Any]:
    x, y = data.get("x"), data.get("y")
    if x is None or y is None:
        return fail("mouse.move requires 'x' and 'y'")
    ms.move(int(x), int(y), absolute=True, duration=float(data.get("duration", 0)))
    return ok(f"Moved to ({x}, {y})")


def _click(data: dict[str, Any], double: bool = False) -> dict[str, Any]:
    button = data.get("button", "left")
    if button not in _VALID_BUTTONS:
        return fail(f"Invalid button '{button}'. Options: {', '.join(_VALID_BUTTONS)}")

    x, y = data.get("x"), data.get("y")
    if x is not None and y is not None:
        ms.move(int(x), int(y), absolute=True)

    if double:
        ms.double_click(button=button)
    else:
        ms.click(button=button)
    return ok(f"{'Double-c' if double else 'C'}licked {button} button")


def _drag(data: dict[str, Any]) -> dict[str, Any]:
    required = ("x1", "y1", "x2", "y2")
    if any(data.get(field) is None for field in required):
        return fail("mouse.drag requires 'x1', 'y1', 'x2', 'y2'")
    ms.drag(
        int(data["x1"]), int(data["y1"]), int(data["x2"]), int(data["y2"]),
        absolute=True, duration=float(data.get("duration", 0.2)),
    )
    return ok(f"Dragged from ({data['x1']}, {data['y1']}) to ({data['x2']}, {data['y2']})")


def _scroll(data: dict[str, Any]) -> dict[str, Any]:
    amount = data.get("amount")
    if amount is None:
        return fail("mouse.scroll requires 'amount'")
    ms.wheel(float(amount))
    return ok(f"Scrolled {amount}")


def _position(_data: dict[str, Any]) -> dict[str, Any]:
    x, y = ms.get_position()
    return ok(f"Cursor at ({x}, {y})", x=x, y=y)


_OPERATIONS = {
    "move": _move,
    "click": _click,
    "double_click": lambda data: _click(data, double=True),
    "drag": _drag,
    "scroll": _scroll,
    "position": _position,
}


@register("mouse")
def mouse_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown mouse operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
