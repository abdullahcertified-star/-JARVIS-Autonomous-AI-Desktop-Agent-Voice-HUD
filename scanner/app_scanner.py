"""Orchestrates every scanner source into a single, deduplicated app database.

Runs each scanner in isolation (one failing source never aborts the whole
scan), merges duplicate entries, generates search aliases automatically, and
persists the result to database/apps.json.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import config
from scanner import (
    scan_desktop,
    scan_path,
    scan_programfiles,
    scan_registry,
    scan_startmenu,
    scan_windowsapps,
)
from scanner.models import AppEntry
from utils.logger import get_logger

SCANNERS = (
    scan_startmenu,
    scan_registry,
    scan_programfiles,
    scan_path,
    scan_windowsapps,
    scan_desktop,
)

# Generic vendor/noise words stripped when generating aliases -- not per-app
# names, just common publisher prefixes that get in the way of a search like
# "chrome" or "packet tracer".
_VENDOR_WORDS = {
    "microsoft", "google", "adobe", "cisco", "oracle", "mozilla",
    "jetbrains", "apple", "amazon", "valve", "epic",
}
_SUFFIX_PATTERN = re.compile(
    r"\s*\((?:64|32)-bit\)|\s*\bx(?:64|86)\b|\s+v?\d+(\.\d+)*\s*$", re.IGNORECASE
)

_KIND_PRIORITY = {"exe": 0, "lnk": 1, "uwp": 2, "file": 3, "folder": 4}


def _run_scanners() -> list[AppEntry]:
    logger = get_logger()
    collected: list[AppEntry] = []

    for module in SCANNERS:
        source_name = module.__name__.rsplit(".", 1)[-1]
        try:
            found = module.scan()
            collected.extend(found)
            logger.info("scanner %s found %d entries", source_name, len(found))
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the scan
            logger.warning("scanner %s failed: %s", source_name, exc)

    return collected


def _generate_aliases(entry: AppEntry) -> set[str]:
    aliases = {a.lower().strip() for a in entry.aliases if a and a.strip()}
    name = entry.name.strip()
    if not name:
        return aliases

    lower_name = name.lower()
    aliases.add(lower_name)

    words = lower_name.split()
    if len(words) > 1 and words[0] in _VENDOR_WORDS:
        aliases.add(" ".join(words[1:]))

    stripped = _SUFFIX_PATTERN.sub("", name).strip().lower()
    if stripped:
        aliases.add(stripped)

    if len(words) > 1 and len(words[0]) >= 3:
        aliases.add(words[0])

    return {a for a in aliases if a}


def _merge_by_path(entries: list[AppEntry]) -> list[AppEntry]:
    merged: dict[str, AppEntry] = {}
    for entry in entries:
        key = entry.dedupe_key()
        if key in merged:
            merged[key].merge(entry)
        else:
            merged[key] = entry
    return list(merged.values())


def _merge_by_name(entries: list[AppEntry]) -> list[AppEntry]:
    """Second pass: collapse entries that share an exact display name but
    were missed by path-based dedup (e.g. a UWP AppID vs. its WindowsApps
    package folder). Keeps whichever kind is most directly launchable."""
    groups: dict[str, list[AppEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.name.strip().lower(), []).append(entry)

    result: list[AppEntry] = []
    for group in groups.values():
        group.sort(key=lambda e: _KIND_PRIORITY.get(e.kind, 99))
        canonical = group[0]
        for extra in group[1:]:
            canonical.merge(extra)
        result.append(canonical)
    return result


def scan_system() -> list[AppEntry]:
    """Runs every scanner and returns a merged, alias-enriched app list."""
    raw = _run_scanners()
    deduped = _merge_by_name(_merge_by_path(raw))

    for entry in deduped:
        entry.aliases = _generate_aliases(entry)

    deduped.sort(key=lambda e: e.name.lower())
    return deduped


def write_database(apps: list[AppEntry]) -> None:
    payload = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "count": len(apps),
        "apps": [app.to_dict() for app in apps],
    }
    config.APPS_JSON_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_database() -> list[AppEntry] | None:
    if not config.APPS_JSON_PATH.exists():
        return None
    try:
        payload = json.loads(config.APPS_JSON_PATH.read_text(encoding="utf-8"))
        return [AppEntry.from_dict(item) for item in payload["apps"]]
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def rescan(verbose: bool = True) -> list[AppEntry]:
    """Full scan + write to disk. This is the only entry point that touches
    every source; call it at startup (if no cache exists) or on demand."""
    if verbose:
        print("Scanning installed applications...")

    started = time.perf_counter()
    apps = scan_system()
    write_database(apps)
    elapsed = time.perf_counter() - started

    if verbose:
        print(f"Found {len(apps)} applications in {elapsed:.1f}s.")

    return apps
