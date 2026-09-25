"""Shared filesystem path resolution for any action that accepts a path.

An AI caller has no reliable way to know the actual Windows account name, so
it will often guess a plausible-looking one (e.g. "C:\\Users\\User\\...")
instead of the real one. Recognizing well-known special-folder names as path
segments and rewriting everything before them to the real home directory
means the caller never needs to get the username right in the first place.
"""

from __future__ import annotations

import os
import re

_SPECIAL_FOLDERS = {
    "desktop": "Desktop",
    "documents": "Documents",
    "my documents": "Documents",
    "downloads": "Downloads",
    "pictures": "Pictures",
    "my pictures": "Pictures",
    "music": "Music",
    "my music": "Music",
    "videos": "Videos",
    "my videos": "Videos",
}


def resolve_path(path: str) -> str:
    """Expands ~/%VARS%, maps drive letters (e.g. 'drive F', 'F:', 'local disk D'),
    and rewrites a guessed-username special-folder path
    (Desktop/Documents/Downloads/...) to the real current user's folder."""
    if not path:
        return ""

    clean = path.strip()

    # Recognize drive letters: "drive F", "drive f:", "F drive", "local disk F", "F:"
    m_drive = re.match(
        r"^(?:(?:the\s+)?drive\s+([a-zA-Z])|([a-zA-Z])\s+drive|local\s+disk\s+([a-zA-Z])|([a-zA-Z]):)[\\/]?$",
        clean,
        re.IGNORECASE,
    )
    if m_drive:
        letter = (m_drive.group(1) or m_drive.group(2) or m_drive.group(3) or m_drive.group(4)).upper()
        return f"{letter}:\\"

    path = os.path.expandvars(os.path.expanduser(path))

    parts = re.split(r"[\\/]+", path)
    for i, part in enumerate(parts):
        real_name = _SPECIAL_FOLDERS.get(part.lower())
        if real_name:
            real_folder = os.path.join(os.path.expanduser("~"), real_name)
            rest = parts[i + 1:]
            return os.path.join(real_folder, *rest) if rest else real_folder

    return path

