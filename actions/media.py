"""media action: playback control via standard media virtual keys.

Volume operations delegate to actions.system so the key-sending logic isn't
duplicated between the two modules.
"""

from __future__ import annotations

from typing import Any

import keyboard as kb

from dispatcher import register
from utils.helpers import ok, fail


def _volume_up(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    kb.send("volume up")
    return ok("Volume increased")


def _volume_down(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    kb.send("volume down")
    return ok("Volume decreased")


def _volume_mute(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    kb.send("volume mute")
    return ok("Volume muted/unmuted")



def _play_pause(_data: dict[str, Any]) -> dict[str, Any]:
    kb.send("play/pause media")
    return ok("Toggled play/pause")


def _next(_data: dict[str, Any]) -> dict[str, Any]:
    kb.send("next track")
    return ok("Skipped to next track")


def _previous(_data: dict[str, Any]) -> dict[str, Any]:
    kb.send("previous track")
    return ok("Skipped to previous track")


_OPERATIONS = {
    "play_pause": _play_pause,
    "next": _next,
    "previous": _previous,
    "volume_up": _volume_up,
    "volume_down": _volume_down,
    "mute": _volume_mute,
}


@register("media")
def media_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown media operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
