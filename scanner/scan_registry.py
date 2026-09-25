"""Discovers apps from the Windows Registry (App Paths + Uninstall keys)."""

from __future__ import annotations

import os
import winreg

from scanner.filters import is_noise_exe
from scanner.models import AppEntry

APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
UNINSTALL_KEYS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
]
HIVES = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)


def _scan_app_paths() -> list[AppEntry]:
    """Every entry under 'App Paths' -> its target exe."""
    entries: list[AppEntry] = []

    for hive in HIVES:
        try:
            root = winreg.OpenKey(hive, APP_PATHS_KEY)
        except OSError:
            continue

        with root:
            index = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1

                try:
                    with winreg.OpenKey(root, subkey_name) as subkey:
                        value, _ = winreg.QueryValueEx(subkey, None)
                except OSError:
                    continue

                if not value:
                    continue
                value = os.path.expandvars(value.strip('"'))
                if not os.path.isfile(value):
                    continue

                name = subkey_name[:-4] if subkey_name.lower().endswith(".exe") else subkey_name
                entries.append(
                    AppEntry(
                        name=name,
                        path=value,
                        kind="exe",
                        source="registry_app_paths",
                        aliases={name.lower()},
                        resolved_target=value,
                    )
                )

    return entries


def _find_executable_in(install_location: str) -> str | None:
    """Best-effort: the largest top-level, non-installer .exe in a dir."""
    try:
        candidates = [
            entry.path
            for entry in os.scandir(install_location)
            if entry.is_file()
            and entry.name.lower().endswith(".exe")
            and not is_noise_exe(entry.name)
        ]
    except OSError:
        return None

    if not candidates:
        return None
    return max(candidates, key=os.path.getsize)


def _scan_uninstall_keys() -> list[AppEntry]:
    """Every entry under 'Uninstall' -> a best-effort resolved executable."""
    entries: list[AppEntry] = []

    for hive in HIVES:
        for base_key in UNINSTALL_KEYS:
            try:
                root = winreg.OpenKey(hive, base_key)
            except OSError:
                continue

            with root:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1

                    try:
                        with winreg.OpenKey(root, subkey_name) as subkey:
                            display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            try:
                                system_component, _ = winreg.QueryValueEx(subkey, "SystemComponent")
                            except OSError:
                                system_component = 0
                            try:
                                install_location, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                            except OSError:
                                install_location = ""
                    except OSError:
                        continue

                    if not display_name or system_component == 1:
                        continue

                    exe = _find_executable_in(install_location) if install_location else None
                    if not exe:
                        continue

                    entries.append(
                        AppEntry(
                            name=display_name,
                            path=exe,
                            kind="exe",
                            source="registry_uninstall",
                            aliases={display_name.lower()},
                            resolved_target=exe,
                        )
                    )

    return entries


def scan() -> list[AppEntry]:
    return _scan_app_paths() + _scan_uninstall_keys()
