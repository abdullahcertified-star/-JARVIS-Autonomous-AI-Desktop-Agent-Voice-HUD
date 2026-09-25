"""Discovers apps by walking Program Files / Program Files (x86).

Bounded-depth so it stays fast, and filtered to skip installer/helper
binaries that would otherwise pollute the app database.
"""

from __future__ import annotations

import os
from pathlib import Path

from scanner.filters import is_generic_folder, is_noise_exe
from scanner.models import AppEntry

PROGRAM_FILES_DIRS = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
]

MAX_DEPTH = 4

_NOISE_DIR_NAMES = {
    "locales", "resources", "redist", "node_modules", "python", "python3",
    "temp", "logs", "cache", "uninstall", "updater", "update",
}


def _iter_exes(root: Path, depth: int):
    if depth > MAX_DEPTH:
        return
    try:
        with os.scandir(root) as scan:
            for entry in scan:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() in _NOISE_DIR_NAMES:
                        continue
                    yield from _iter_exes(Path(entry.path), depth + 1)
                elif entry.is_file() and entry.name.lower().endswith(".exe"):
                    yield Path(entry.path)
    except (PermissionError, OSError):
        return


def scan() -> list[AppEntry]:
    entries: list[AppEntry] = []

    for base in PROGRAM_FILES_DIRS:
        if not base.exists():
            continue

        for exe in _iter_exes(base, depth=1):
            if is_noise_exe(exe.name):
                continue

            name = exe.stem
            parent_name = exe.parent.name

            aliases = {name.lower()}
            if not is_generic_folder(parent_name):
                aliases.add(parent_name.lower())

            entries.append(
                AppEntry(
                    name=name,
                    path=str(exe),
                    kind="exe",
                    source="program_files",
                    aliases=aliases,
                    resolved_target=str(exe),
                )
            )

    return entries
