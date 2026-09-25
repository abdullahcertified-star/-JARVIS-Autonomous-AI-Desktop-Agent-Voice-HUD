"""system action: power state, volume, machine status, and running commands.

Relative volume control is implemented here (via the standard media virtual
keys) and reused by actions/media.py so the key-sending logic lives in one
place. Absolute volume (set_volume) goes through pycaw/Core Audio instead,
since key presses can't jump straight to a target percentage.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import time
from typing import Any

import comtypes
import keyboard as kb
import psutil
from pycaw.pycaw import AudioUtilities

import config
from dispatcher import register
from utils.helpers import fail, ok


def volume_up(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    kb.send("volume up")
    return ok("Volume increased")


def volume_down(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    kb.send("volume down")
    return ok("Volume decreased")


def volume_mute(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    kb.send("volume mute")
    return ok("Volume muted/unmuted")


def _get_volume_endpoint():
    # Flask can hand this request to a thread comtypes/pycaw has never seen
    # before, and COM must be initialized per-thread. Safe to call every
    # time -- comtypes no-ops if this thread is already initialized.
    comtypes.CoInitialize()
    return AudioUtilities.GetSpeakers().EndpointVolume


def _set_volume(data: dict[str, Any]) -> dict[str, Any]:
    level = data.get("level")
    if level is None:
        return fail("system.set_volume requires 'level' (0-100)")
    try:
        level = float(level)
    except (TypeError, ValueError):
        return fail("'level' must be a number between 0 and 100")
    if not 0 <= level <= 100:
        return fail("'level' must be between 0 and 100")

    _get_volume_endpoint().SetMasterVolumeLevelScalar(level / 100, None)
    return ok(f"Volume set to {round(level)}%", level=round(level))


def _shutdown(_data: dict[str, Any]) -> dict[str, Any]:
    subprocess.Popen(["shutdown", "/s", "/t", "0"])
    return ok("Shutting down")


def _restart(_data: dict[str, Any]) -> dict[str, Any]:
    subprocess.Popen(["shutdown", "/r", "/t", "0"])
    return ok("Restarting")


def _lock(_data: dict[str, Any]) -> dict[str, Any]:
    ctypes.windll.user32.LockWorkStation()
    return ok("Locked workstation")


def _sleep(_data: dict[str, Any]) -> dict[str, Any]:
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return ok("Sleeping")


def _status(_data: dict[str, Any]) -> dict[str, Any]:
    battery = psutil.sensors_battery()
    volume = _get_volume_endpoint()
    return ok(
        "System status",
        cpu_percent=psutil.cpu_percent(interval=None),
        memory_percent=psutil.virtual_memory().percent,
        battery_percent=battery.percent if battery else None,
        uptime_seconds=round(time.time() - psutil.boot_time()),
        volume_percent=round(volume.GetMasterVolumeLevelScalar() * 100),
        muted=bool(volume.GetMute()),
    )


def _run_command(data: dict[str, Any]) -> dict[str, Any]:
    command = data.get("command")
    if not command or not isinstance(command, str):
        return fail("system.run_command requires 'command' (string)")

    timeout = data.get("timeout", config.RUN_COMMAND_DEFAULT_TIMEOUT)
    try:
        timeout = min(float(timeout), config.RUN_COMMAND_MAX_TIMEOUT)
    except (TypeError, ValueError):
        return fail("'timeout' must be a number of seconds")

    cwd = data.get("cwd") or None

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return fail(f"Command timed out after {timeout}s: {command}")
    except OSError as exc:
        return fail(f"Failed to run command: {exc}")

    respond = ok if result.returncode == 0 else fail
    return respond(
        f"Command exited with code {result.returncode}",
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _empty_recycle_bin(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        # 7 = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7)
        if res == 0 or res == -2147418113:
            return ok("Recycle Bin emptied successfully")
        return ok("Recycle Bin emptied")
    except Exception as exc:
        return fail(f"Failed to empty Recycle Bin: {exc}")


def _close_app(data: dict[str, Any]) -> dict[str, Any]:
    target = data.get("target") or data.get("app") or data.get("name")
    if not target:
        return fail("close_app requires 'target'")
    target_clean = str(target).lower().strip().replace(".exe", "")
    closed = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info["name"] or "").lower()
            if target_clean in name or name.startswith(target_clean):
                p.terminate()
                closed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if closed > 0:
        return ok(f"Closed {closed} process(es) matching '{target}'", target=target, count=closed)
    res = subprocess.run(["taskkill", "/f", "/im", f"{target_clean}.exe"], capture_output=True, text=True)
    if res.returncode == 0:
        return ok(f"Closed '{target}'", target=target)
    return fail(f"No running application found matching '{target}'")


def _list_processes(data: dict[str, Any]) -> dict[str, Any]:
    limit = int(data.get("limit", 10))
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            name = p.info["name"] or ""
            mem = p.info["memory_percent"] or 0.0
            if name.lower().endswith(".exe") and mem > 0.3:
                procs.append({
                    "name": name,
                    "pid": p.info["pid"],
                    "ram_percent": round(mem, 1),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x["ram_percent"], reverse=True)
    return ok(f"Listed {min(len(procs), limit)} active applications", processes=procs[:limit])


def _screen_brightness(data: dict[str, Any]) -> dict[str, Any]:
    level = data.get("level")
    if level is None:
        return fail("screen_brightness requires 'level' (0-100)")
    try:
        level = max(0, min(100, int(level)))
        ps_cmd = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=5)
        return ok(f"Screen brightness set to {level}%", level=level)
    except Exception as exc:
        return fail(f"Could not adjust brightness: {exc}")


def _wifi_info(_data: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        res = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=4)
        ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", res.stdout, re.MULTILINE)
        signal = re.search(r"^\s*Signal\s*:\s*(.+)$", res.stdout, re.MULTILINE)
        state = re.search(r"^\s*State\s*:\s*(.+)$", res.stdout, re.MULTILINE)
        ssid_str = ssid.group(1).strip() if ssid else "Not connected"
        signal_str = signal.group(1).strip() if signal else "N/A"
        state_str = state.group(1).strip() if state else "disconnected"
        return ok(f"Wi-Fi {state_str}: {ssid_str} (Signal: {signal_str})", ssid=ssid_str, signal=signal_str, state=state_str)
    except Exception as exc:
        return fail(f"Failed to check Wi-Fi: {exc}")


def _ping(data: dict[str, Any]) -> dict[str, Any]:
    host = data.get("host") or data.get("target") or "8.8.8.8"
    try:
        res = subprocess.run(["ping", "-n", "2", "-w", "1000", str(host)], capture_output=True, text=True, timeout=4)
        if res.returncode == 0:
            time_m = re.search(r"Average\s*=\s*(\d+ms)", res.stdout)
            avg = time_m.group(1) if time_m else "OK"
            return ok(f"Ping to {host} succeeded ({avg})", host=host, average=avg)
        return fail(f"Ping to {host} failed (host unreachable)")
    except Exception as exc:
        return fail(f"Ping error: {exc}")


_OPERATIONS = {
    "shutdown": _shutdown,
    "restart": _restart,
    "lock": _lock,
    "sleep": _sleep,
    "volume_up": volume_up,
    "volume_down": volume_down,
    "mute": volume_mute,
    "set_volume": _set_volume,
    "status": _status,
    "run_command": _run_command,
    "empty_recycle_bin": _empty_recycle_bin,
    "close_app": _close_app,
    "list_processes": _list_processes,
    "screen_brightness": _screen_brightness,
    "wifi_info": _wifi_info,
    "ping": _ping,
}


@register("system")
def system_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown system operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
