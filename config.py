"""Central configuration for the JARVIS desktop automation server."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR: Path = Path(__file__).resolve().parent

DATABASE_DIR: Path = BASE_DIR / "database"
APPS_JSON_PATH: Path = DATABASE_DIR / "apps.json"

LOGS_DIR: Path = BASE_DIR / "logs"
LOG_FILE: Path = LOGS_DIR / "jarvis.log"

SCREENSHOTS_DIR: Path = BASE_DIR / "screenshots"

HOST: str = os.getenv("JARVIS_HOST", "0.0.0.0")
PORT: int = int(os.getenv("JARVIS_PORT", "5000"))
DEBUG: bool = os.getenv("JARVIS_DEBUG", "true").lower() in {"1", "true", "yes"}

# Minimum RapidFuzz similarity score (0-100) for an app search match to be accepted.
APP_SEARCH_CUTOFF: int = int(os.getenv("JARVIS_APP_SEARCH_CUTOFF", "85"))

# Default/maximum seconds a system.run_command call is allowed to block for.
RUN_COMMAND_DEFAULT_TIMEOUT: int = int(os.getenv("JARVIS_RUN_COMMAND_TIMEOUT", "30"))
RUN_COMMAND_MAX_TIMEOUT: int = int(os.getenv("JARVIS_RUN_COMMAND_MAX_TIMEOUT", "120"))

# Cap on how many characters explorer.read returns from a single file.
FILE_READ_MAX_CHARS: int = int(os.getenv("JARVIS_FILE_READ_MAX_CHARS", "200000"))

# Gemini AI Agent configuration (Google GenAI SDK)
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
JARVIS_GEMINI_MODEL: str = os.getenv("JARVIS_GEMINI_MODEL", "gemini-flash-lite-latest")

for _dir in (DATABASE_DIR, LOGS_DIR, SCREENSHOTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
