"""Windows .lnk shortcut resolution, shared by the Start Menu and Desktop scanners."""

from __future__ import annotations

import functools
from dataclasses import dataclass

import win32com.client


@functools.lru_cache(maxsize=1)
def _shell():
    return win32com.client.Dispatch("WScript.Shell")


@dataclass
class ResolvedShortcut:
    target: str
    arguments: str


def resolve_shortcut(lnk_path: str) -> ResolvedShortcut | None:
    """Resolves a .lnk's target executable and its launch arguments.

    Many shortcuts (Node.js tools, VS dev prompts, etc.) point at a generic
    host like cmd.exe/powershell.exe and rely entirely on -Arguments to be
    distinct apps -- callers must not dedupe on target path alone.
    """
    try:
        shortcut = _shell().CreateShortCut(lnk_path)
        target = shortcut.Targetpath
        if not target:
            return None
        return ResolvedShortcut(target=target, arguments=shortcut.Arguments or "")
    except Exception:
        return None
