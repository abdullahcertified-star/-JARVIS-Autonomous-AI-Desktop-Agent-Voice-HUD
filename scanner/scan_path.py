"""Discovers CLI tools and apps sitting directly on the PATH."""

from __future__ import annotations

import os
from pathlib import Path

from scanner.models import AppEntry


def scan() -> list[AppEntry]:
    entries: list[AppEntry] = []
    seen: set[str] = set()

    for raw_dir in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(raw_dir.strip('"'))
        if not directory.is_dir():
            continue

        try:
            with os.scandir(directory) as scan:
                for entry in scan:
                    if not (entry.is_file() and entry.name.lower().endswith(".exe")):
                        continue
                    name = Path(entry.name).stem
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)

                    entries.append(
                        AppEntry(
                            name=name,
                            path=entry.path,
                            kind="exe",
                            source="path",
                            aliases={key},
                            resolved_target=entry.path,
                        )
                    )
        except (PermissionError, OSError):
            continue

    return entries
