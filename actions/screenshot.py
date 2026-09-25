"""screenshot action: capture the full screen or a region to disk."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PIL import Image, ImageGrab

import config
from dispatcher import register
from utils.helpers import fail, ok


def capture_image(region: list[int] | None = None) -> Image.Image:
    """Grabs a screenshot as a PIL Image. region is [x, y, width, height]."""
    if region:
        x, y, w, h = region
        return ImageGrab.grab(bbox=(x, y, x + w, y + h))
    return ImageGrab.grab()


def _capture(data: dict[str, Any]) -> dict[str, Any]:
    region = data.get("region")
    if region is not None and (not isinstance(region, list) or len(region) != 4):
        return fail("screenshot.capture 'region' must be [x, y, width, height]")

    image = capture_image(region)

    filename = f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
    path = config.SCREENSHOTS_DIR / filename
    image.save(path)

    return ok(f"Screenshot saved to {path}", path=str(path))


_OPERATIONS = {
    "capture": _capture,
}


@register("screenshot")
def screenshot_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown screenshot operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
