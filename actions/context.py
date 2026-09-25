"""context action: ambient presence, focus/DND management, and quiet hours."""

from __future__ import annotations

import ctypes
import datetime
import logging
import platform
import time
from typing import Any

from dispatcher import register
from utils.helpers import fail, ok

logger = logging.getLogger(__name__)

# State variables
_focus_active: bool = False
_focus_start: float | None = None
_focus_goal: str = ""

_quiet_hours_enabled: bool = True
_quiet_hours_start_hour: int = 23  # 11:00 PM
_quiet_hours_end_hour: int = 7     # 07:00 AM


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


def get_idle_seconds() -> float:
    """Returns how many seconds have elapsed since the user's last keyboard or mouse input."""
    if platform.system() != "Windows":
        return 0.0

    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0.0, float(millis) / 1000.0)
    except Exception as exc:
        logger.debug("Failed to query GetLastInputInfo: %s", exc)
    return 0.0


def get_presence_state() -> dict[str, Any]:
    """Determines if the user is actively working, idle, or away."""
    idle = get_idle_seconds()
    if idle < 60.0:
        state = "active"
    elif idle < 300.0:
        state = "idle"
    else:
        state = "away"

    return {
        "idle_seconds": round(idle, 1),
        "state": state,
    }


def is_quiet_hours() -> bool:
    """Checks whether the current local time falls within configured quiet hours."""
    if not _quiet_hours_enabled:
        return False

    now_hour = datetime.datetime.now().hour
    if _quiet_hours_start_hour > _quiet_hours_end_hour:
        # Crosses midnight, e.g. 23:00 -> 07:00
        return now_hour >= _quiet_hours_start_hour or now_hour < _quiet_hours_end_hour
    else:
        return _quiet_hours_start_hour <= now_hour < _quiet_hours_end_hour


def should_suppress_alert(severity: str = "warning") -> bool:
    """Determines whether a background advisory alert should be silenced based on ambient state."""
    if severity == "critical":
        return False  # Critical alerts (e.g. dying battery) are never suppressed

    if _focus_active:
        return True

    if is_quiet_hours():
        return True

    return False


def enable_focus(goal: str = "") -> dict[str, Any]:
    """Activates focus / do not disturb mode."""
    global _focus_active, _focus_start, _focus_goal
    _focus_active = True
    _focus_start = time.time()
    _focus_goal = goal.strip()

    msg = "Positive sir, Focus Mode is now active. Non-critical interruptions are suppressed."
    if _focus_goal:
        msg += f" Target objective: {_focus_goal}."
    return ok(msg, focus_active=True, goal=_focus_goal, start_time=_focus_start)


def disable_focus() -> dict[str, Any]:
    """Deactivates focus / do not disturb mode."""
    global _focus_active, _focus_start, _focus_goal
    if not _focus_active:
        return ok("Focus Mode is not currently active.", focus_active=False)

    duration_sec = time.time() - (_focus_start or time.time())
    mins = int(duration_sec // 60)
    goal = _focus_goal

    _focus_active = False
    _focus_start = None
    _focus_goal = ""

    msg = f"Positive sir, Focus Mode deactivated. Total focus session: {mins} minutes"
    if goal:
        msg += f" on '{goal}'."
    else:
        msg += "."
    return ok(msg, focus_active=False, duration_minutes=mins, goal=goal)


def get_focus_status() -> dict[str, Any]:
    """Retrieves current focus mode state and elapsed duration."""
    if not _focus_active:
        return ok("Focus Mode is currently inactive.", focus_active=False)

    duration_sec = time.time() - (_focus_start or time.time())
    mins = int(duration_sec // 60)
    msg = f"Focus Mode is active ({mins} minutes elapsed)"
    if _focus_goal:
        msg += f" with objective: {_focus_goal}."
    else:
        msg += "."
    return ok(msg, focus_active=True, elapsed_minutes=mins, goal=_focus_goal)


def get_ambient_context() -> dict[str, Any]:
    """Retrieves full ambient context snapshot: presence, focus mode, and quiet hours."""
    presence = get_presence_state()
    quiet = is_quiet_hours()
    idle_sec = presence["idle_seconds"]
    idle_min = int(idle_sec // 60)
    state = presence["state"]

    parts = [f"User presence: {state} (idle: {idle_min}m {int(idle_sec % 60)}s)"]
    if _focus_active:
        duration_sec = time.time() - (_focus_start or time.time())
        parts.append(f"Focus Mode: ON ({int(duration_sec // 60)}m elapsed)")
    else:
        parts.append("Focus Mode: OFF")

    parts.append(f"Quiet Hours: {'Active' if quiet else 'Inactive'}")

    msg = f"Ambient Context: {', '.join(parts)}."
    return ok(
        msg,
        presence=presence,
        focus_active=_focus_active,
        quiet_hours_active=quiet,
        suppress_alerts=should_suppress_alert(),
    )


def _set_quiet_hours(data: dict[str, Any]) -> dict[str, Any]:
    global _quiet_hours_enabled, _quiet_hours_start_hour, _quiet_hours_end_hour
    start = data.get("start_hour")
    end = data.get("end_hour")
    enabled = data.get("enabled")

    if enabled is not None:
        _quiet_hours_enabled = bool(enabled)
    if start is not None:
        try:
            _quiet_hours_start_hour = int(start) % 24
        except (ValueError, TypeError):
            return fail("start_hour must be an integer between 0 and 23.")
    if end is not None:
        try:
            _quiet_hours_end_hour = int(end) % 24
        except (ValueError, TypeError):
            return fail("end_hour must be an integer between 0 and 23.")

    status_str = "enabled" if _quiet_hours_enabled else "disabled"
    msg = f"Quiet hours {status_str} ({_quiet_hours_start_hour:02d}:00 to {_quiet_hours_end_hour:02d}:00)."
    return ok(msg, enabled=_quiet_hours_enabled, start=_quiet_hours_start_hour, end=_quiet_hours_end_hour)


_OPERATIONS = {
    "enable_focus": lambda d: enable_focus(str(d.get("goal", ""))),
    "start_focus": lambda d: enable_focus(str(d.get("goal", ""))),
    "disable_focus": lambda _d: disable_focus(),
    "stop_focus": lambda _d: disable_focus(),
    "get_focus_status": lambda _d: get_focus_status(),
    "status": lambda _d: get_ambient_context(),
    "get_ambient_context": lambda _d: get_ambient_context(),
    "get_presence": lambda _d: ok(
        f"Presence: {get_presence_state()['state']} (idle for {int(get_presence_state()['idle_seconds'])} seconds)",
        **get_presence_state(),
    ),
    "set_quiet_hours": _set_quiet_hours,
}


@register("context")
def context_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown context operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
