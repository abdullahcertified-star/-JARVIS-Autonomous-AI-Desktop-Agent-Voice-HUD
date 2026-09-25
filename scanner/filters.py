"""Shared noise-filtering heuristics used by multiple scanners."""

from __future__ import annotations

import re

# Executable name looks like an installer/updater/helper, not the app itself.
NOISE_EXE_PATTERN = re.compile(
    r"unins|setup|redist|vcredist|crashpad|updater|update\.exe|helper|"
    r"installer|^vc_|\.tmp$|elevat|report|breakpad|"
    r"^(cleanup|repair|maintenance)",
    re.IGNORECASE,
)

# Folder names too generic to be useful as a search alias on their own
# (many unrelated tools ship a "bin" or "cmd" subfolder).
GENERIC_FOLDER_NAMES = {
    "bin", "cmd", "tools", "app", "apps", "application", "applications",
    "release", "debug", "build", "dist", "out", "resources", "res",
    "x64", "x86", "win32", "win64", "program", "programs", "core",
    "runtime", "lib", "libs", "shared", "common", "data",
}


def is_noise_exe(filename: str) -> bool:
    return bool(NOISE_EXE_PATTERN.search(filename))


def is_generic_folder(name: str) -> bool:
    return name.lower() in GENERIC_FOLDER_NAMES


# Shell/script hosts that many unrelated shortcuts point at, distinguished
# only by their launch arguments -- never useful as a search alias.
GENERIC_HOST_EXES = {
    "cmd", "powershell", "pwsh", "rundll32", "wscript", "cscript",
    "mshta", "conhost", "explorer", "wsl",
}


def is_generic_host(exe_stem: str) -> bool:
    return exe_stem.lower() in GENERIC_HOST_EXES
