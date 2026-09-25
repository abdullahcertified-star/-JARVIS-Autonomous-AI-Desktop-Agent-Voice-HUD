"""Discovers Microsoft Store / UWP apps via Get-StartApps, plus a best-effort
listing of the WindowsApps folder (usually ACL-locked for normal users, so
failures here are expected and silently skipped).
"""

from __future__ import annotations

import json
import os
import subprocess

from scanner.models import AppEntry

WINDOWS_APPS_DIR = os.path.expandvars(r"%ProgramFiles%\WindowsApps")


def _scan_start_apps() -> list[AppEntry]:
    """Uses PowerShell's Get-StartApps to list UWP/Store apps and their AppID."""
    entries: list[AppEntry] = []

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        data = json.loads(result.stdout or "[]")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return entries

    if isinstance(data, dict):
        data = [data]

    for item in data:
        name = (item.get("Name") or "").strip()
        app_id = (item.get("AppID") or "").strip()
        if not name or "!" not in app_id:
            continue  # not a UWP/Store package -- covered by other scanners

        entries.append(
            AppEntry(
                name=name,
                path=app_id,
                kind="uwp",
                source="windows_apps",
                aliases={name.lower()},
            )
        )

    return entries


def _scan_windows_apps_folder() -> list[AppEntry]:
    """Best-effort: package folder names as extra aliases when readable."""
    entries: list[AppEntry] = []

    try:
        with os.scandir(WINDOWS_APPS_DIR) as scan:
            for pkg in scan:
                if not pkg.is_dir(follow_symlinks=False):
                    continue
                # Package dirs look like 'Vendor.AppName_1.0.0.0_x64__8wekyb3d8bbwe'
                display = pkg.name.split("_")[0].split(".")[-1]
                if not display:
                    continue
                entries.append(
                    AppEntry(
                        name=display,
                        path=pkg.path,
                        kind="folder",
                        source="windows_apps_folder",
                        aliases={display.lower()},
                    )
                )
    except (PermissionError, OSError):
        pass  # Expected: WindowsApps is locked down for normal users.

    return entries


def scan() -> list[AppEntry]:
    return _scan_start_apps() + _scan_windows_apps_folder()
