"""Shared data model produced by every scanner and stored in apps.json."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

AppKind = Literal["exe", "lnk", "uwp", "folder", "file"]


@dataclass
class AppEntry:
    """A single discovered, launchable application."""

    name: str
    path: str
    kind: AppKind
    source: str
    aliases: set[str] = field(default_factory=set)
    resolved_target: str | None = None
    """Best-effort resolved executable path, used only to dedupe entries
    across scanners (e.g. a Start Menu .lnk and an App Paths registry entry
    that both point at chrome.exe). Not persisted to apps.json."""
    target_args: str = ""
    """Arguments a .lnk passes to its target, if any. Shortcuts to a shared
    host like cmd.exe/powershell.exe are only the same app when their
    arguments also match -- otherwise they're distinct tools (e.g. a plain
    Command Prompt vs. a "Developer PowerShell for VS" shortcut)."""

    def dedupe_key(self) -> str:
        """Case-insensitive key identifying the underlying application."""
        target = self.resolved_target or self.path
        key = os.path.normcase(os.path.normpath(target))
        args = self.target_args.strip().lower()
        return f"{key}::{args}" if args else key

    def merge(self, other: "AppEntry") -> None:
        """Folds another entry describing the same app into this one."""
        self.aliases |= other.aliases
        self.aliases.add(other.name.lower())
        if len(other.name) > len(self.name):
            # Prefer the more descriptive / human-readable display name.
            self.name = other.name

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "aliases": sorted(self.aliases),
            "path": self.path,
            "kind": self.kind,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppEntry":
        return cls(
            name=data["name"],
            path=data["path"],
            kind=data["kind"],
            source=data.get("source", "cache"),
            aliases=set(data.get("aliases", [])),
        )
