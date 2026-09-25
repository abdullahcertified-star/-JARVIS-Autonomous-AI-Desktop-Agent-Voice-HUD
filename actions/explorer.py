"""explorer action: open/reveal in Explorer, and file CRUD (read/create/update/delete).

Delete goes through send2trash (Recycle Bin), not a permanent unlink, so an
AI mistake here is recoverable the same way an accidental Explorer delete is.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from send2trash import send2trash

import config
from dispatcher import register
from utils.helpers import fail, ok
from utils.paths import resolve_path as _resolve_path

_MAX_DIR_ENTRIES = 500


def _open(data: dict[str, Any]) -> dict[str, Any]:
    path = data.get("path")
    if not path:
        return fail("explorer.open requires 'path'")
    if not os.path.exists(path):
        return fail(f"Path does not exist: {path}")
    os.startfile(path)  # noqa: S606
    return ok(f"Opened {path}")


def _reveal(data: dict[str, Any]) -> dict[str, Any]:
    path = data.get("path")
    if not path:
        return fail("explorer.reveal requires 'path'")
    if not os.path.exists(path):
        return fail(f"Path does not exist: {path}")
    subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
    return ok(f"Revealed {path} in Explorer")


def _list_dir(path: str) -> dict[str, Any]:
    entries = []
    with os.scandir(path) as scan:
        for entry in scan:
            if len(entries) >= _MAX_DIR_ENTRIES:
                break
            try:
                size = entry.stat().st_size if entry.is_file() else None
            except OSError:
                size = None
            entries.append({
                "name": entry.name,
                "type": "folder" if entry.is_dir() else "file",
                "size_bytes": size,
            })
    return ok(f"Listed {len(entries)} item(s) in {path}", path=path, entries=entries)


def _read_file(path: str) -> dict[str, Any]:
    size = os.path.getsize(path)
    limit = config.FILE_READ_MAX_CHARS
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(limit + 1)
    truncated = len(content) > limit
    if truncated:
        content = content[:limit]
    return ok(
        f"Read {path}",
        path=path,
        content=content,
        truncated=truncated,
        size_bytes=size,
    )


def _read(data: dict[str, Any]) -> dict[str, Any]:
    path = data.get("path")
    if not path:
        return fail("explorer.read requires 'path'")
    if not os.path.exists(path):
        return fail(f"Path does not exist: {path}")
    return _list_dir(path) if os.path.isdir(path) else _read_file(path)


def _create(data: dict[str, Any]) -> dict[str, Any]:
    path = data.get("path")
    if not path:
        return fail("explorer.create requires 'path'")

    if data.get("is_folder"):
        os.makedirs(path, exist_ok=True)
        return ok(f"Created folder {path}", path=path)

    if os.path.exists(path):
        return fail(f"{path} already exists -- use the 'update' operation to modify it")

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    content = data.get("content", "")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return ok(f"Created {path}", path=path, bytes_written=len(content.encode("utf-8")))


def _update(data: dict[str, Any]) -> dict[str, Any]:
    path = data.get("path")
    if not path:
        return fail("explorer.update requires 'path'")
    content = data.get("content")
    if content is None:
        return fail("explorer.update requires 'content'")
    if not os.path.isfile(path):
        return fail(f"{path} doesn't exist as a file -- use the 'create' operation first")

    mode = "a" if data.get("append") else "w"
    with open(path, mode, encoding="utf-8") as f:
        f.write(content)
    verb = "Appended to" if data.get("append") else "Updated"
    return ok(f"{verb} {path}", path=path, bytes_written=len(content.encode("utf-8")))


def _delete(data: dict[str, Any]) -> dict[str, Any]:
    path = data.get("path")
    if not path:
        return fail("explorer.delete requires 'path'")
    if not os.path.exists(path):
        return fail(f"Path does not exist: {path}")

    send2trash(os.path.abspath(path))
    return ok(f"Moved {path} to the Recycle Bin", path=path)


def _search(data: dict[str, Any]) -> dict[str, Any]:
    query = data.get("query")
    if not query:
        return fail("explorer.search requires 'query'")
    query_clean = str(query).lower().strip()
    root_folder = data.get("root_folder") or data.get("path")

    roots = []
    if root_folder and os.path.exists(root_folder):
        roots = [os.path.abspath(root_folder)]
    else:
        user_home = os.path.expanduser("~")
        for sub in ("Desktop", "Documents", "Downloads"):
            p = os.path.join(user_home, sub)
            if os.path.exists(p):
                roots.append(p)
        if not roots:
            roots = [os.getcwd()]

    matches = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", "appdata", "__pycache__", "$recycle.bin", "site-packages"}

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in skip_dirs and not d.startswith(".")]
            for f in filenames:
                if query_clean in f.lower():
                    full_p = os.path.join(dirpath, f)
                    try:
                        sz = os.path.getsize(full_p)
                    except OSError:
                        sz = None
                    matches.append({"name": f, "path": full_p, "size_bytes": sz})
                    if len(matches) >= 15:
                        break
            if len(matches) >= 15:
                break
        if len(matches) >= 15:
            break

    if not matches:
        return ok(f"No files found matching '{query}'", matches=[])
    return ok(f"Found {len(matches)} file(s) matching '{query}'", matches=matches)


_OPERATIONS = {
    "open": _open,
    "reveal": _reveal,
    "read": _read,
    "create": _create,
    "update": _update,
    "delete": _delete,
    "search": _search,
}


@register("explorer")
def explorer_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown explorer operation '{operation}'. Options: {', '.join(_OPERATIONS)}")

    if data.get("path"):
        data = {**data, "path": _resolve_path(data["path"])}

    return handler(data)
