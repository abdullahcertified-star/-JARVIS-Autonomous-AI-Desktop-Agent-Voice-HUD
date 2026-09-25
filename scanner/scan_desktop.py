"""Discovers apps from the user and public Desktop (.lnk and .url shortcuts)."""

from __future__ import annotations

import os
from pathlib import Path

from scanner.filters import is_generic_host
from scanner.models import AppEntry
from scanner.shortcuts import resolve_shortcut

DESKTOP_DIRS = [
    Path(os.environ.get("USERPROFILE", "")) / "Desktop",
    Path(os.environ.get("PUBLIC", "")) / "Desktop",
]


def scan() -> list[AppEntry]:
    """Walks Desktop folders and returns one entry per shortcut found."""
    entries: list[AppEntry] = []

    for base in DESKTOP_DIRS:
        if not base.exists():
            continue

        for lnk in base.glob("*.lnk"):
            name = lnk.stem
            resolved = resolve_shortcut(str(lnk))
            target = resolved.target if resolved and os.path.isfile(resolved.target) else None

            entry = AppEntry(
                name=name,
                path=str(lnk),
                kind="lnk",
                source="desktop",
                aliases={name.lower()},
                resolved_target=target,
                target_args=resolved.arguments if resolved else "",
            )
            if target and not is_generic_host(Path(target).stem):
                entry.aliases.add(Path(target).stem.lower())
            entries.append(entry)

        for url_file in base.glob("*.url"):
            name = url_file.stem
            entries.append(
                AppEntry(
                    name=name,
                    path=str(url_file),
                    kind="file",
                    source="desktop",
                    aliases={name.lower()},
                )
            )

    return entries
