"""Discovers apps from the user and public Start Menu (.lnk shortcuts)."""

from __future__ import annotations

import os
from pathlib import Path

from scanner.filters import is_generic_host
from scanner.models import AppEntry
from scanner.shortcuts import resolve_shortcut

START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]


def scan() -> list[AppEntry]:
    """Walks the Start Menu program folders and returns one entry per shortcut."""
    entries: list[AppEntry] = []

    for base in START_MENU_DIRS:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            name = lnk.stem
            resolved = resolve_shortcut(str(lnk))
            target = resolved.target if resolved and os.path.isfile(resolved.target) else None

            entry = AppEntry(
                name=name,
                path=str(lnk),
                kind="lnk",
                source="start_menu",
                aliases={name.lower()},
                resolved_target=target,
                target_args=resolved.arguments if resolved else "",
            )
            if target and not is_generic_host(Path(target).stem):
                entry.aliases.add(Path(target).stem.lower())
            entries.append(entry)

    return entries
