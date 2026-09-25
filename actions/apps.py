"""open_app / refresh_apps: launches applications discovered by the scanner."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from dispatcher import register
from scanner.models import AppEntry
from search.app_search import get_index, refresh_index
from utils.helpers import fail, first_present, ok
from utils.paths import resolve_path


def _launch(app: AppEntry) -> None:
    if app.kind == "uwp":
        subprocess.Popen(["explorer.exe", f"shell:appsFolder\\{app.path}"])
    elif app.kind in ("lnk", "file", "folder"):
        os.startfile(app.path)  # noqa: S606 - resolves shortcuts/opens folders natively
    elif app.kind == "exe":
        subprocess.Popen([app.path])
    else:
        raise ValueError(f"Unknown app kind: {app.kind}")


@register("open_app")
def open_app(data: dict[str, Any]) -> dict[str, Any]:
    query = first_present(data, "target", "app", "app_name", default="").strip()
    if not query:
        return fail("No application specified")

    # Handle phonetic mishearings (e.g. "open the drive app" -> Drive F or File Explorer)
    if re.search(r"^(?:the\s+)?drive\s+app$", query, re.IGNORECASE):
        if os.path.exists("F:\\"):
            try:
                os.startfile("F:\\")  # noqa: S606
                return ok("Opened Drive F:\\ in File Explorer", matched="F:\\")
            except OSError as exc:
                return fail(f"Failed to open Drive F:\\: {exc}")
        subprocess.Popen(["explorer.exe"])
        return ok("Opened File Explorer", matched="File Explorer")

    if re.search(r"^(?:drives|this\s+pc|my\s+computer)$", query, re.IGNORECASE):
        subprocess.Popen(["explorer.exe", "shell:MyComputerFolder"])
        return ok("Opened This PC in File Explorer", matched="This PC")

    # "Open Application" also covers opening a specific file/folder by path
    # (e.g. a document on the Desktop or a drive like 'drive F') -- try that directly before falling
    # back to fuzzy-matching against installed applications, so a caller
    # doesn't need to know to use a different tool for files vs. programs.
    resolved_path = resolve_path(query)
    if os.path.exists(resolved_path):
        try:
            os.startfile(resolved_path)  # noqa: S606
        except OSError as exc:
            return fail(f"Failed to open {resolved_path}: {exc}")
        return ok(f"Opened {resolved_path}", matched=resolved_path)


    app = get_index().find(query)
    if app is None:
        return fail(f"'{query}' is not installed or could not be found")

    try:
        _launch(app)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as JSON
        return fail(f"Failed to launch {app.name}: {exc}")

    return ok(f"Opened {app.name}", matched=app.name)


@register("refresh_apps")
def refresh_apps(_data: dict[str, Any]) -> dict[str, Any]:
    count = refresh_index()
    return ok(f"Application database refreshed: {count} applications found", count=count)
