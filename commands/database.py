"""SQLite and In-Memory Search Engine for the JARVIS Command Knowledge Base.

Stores all 492 commands extracted from the Windows Command Master Reference PDF,
providing instant full-text search, exact lookup, category browsing, and
fuzzy matching for natural language queries.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from rapidfuzz import fuzz, process

import config
from commands.catalog import DEFAULT_PDF_PATH, build_and_save_catalog

DB_PATH = config.DATABASE_DIR / "commands.db"
JSON_PATH = config.DATABASE_DIR / "commands.json"


class CommandDatabase:
    """High-performance local SQLite and cached vector/fuzzy store for Windows commands."""

    def __init__(self, db_path: Path = DB_PATH, json_path: Path = JSON_PATH) -> None:
        self.db_path = Path(db_path)
        self.json_path = Path(json_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_initialized()
        self._cache: list[dict[str, Any]] = []
        self._load_cache()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_initialized(self) -> None:
        """Initializes SQLite schema and populates from JSON if table is empty."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS commands (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        clean_name TEXT NOT NULL,
                        category TEXT NOT NULL,
                        shell TEXT NOT NULL,
                        description TEXT NOT NULL,
                        examples TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        requires_admin INTEGER NOT NULL,
                        destructive INTEGER NOT NULL,
                        template TEXT NOT NULL,
                        intents TEXT NOT NULL,
                        extra_info TEXT
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_clean_name ON commands(clean_name);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_category ON commands(category);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_risk ON commands(risk_level);")

                count = conn.execute("SELECT COUNT(*) FROM commands;").fetchone()[0]
                if count == 0:
                    self._populate_database(conn)
        finally:
            conn.close()

    def _populate_database(self, conn: sqlite3.Connection) -> None:
        """Populates the database from JSON or regenerates from the master PDF."""
        if not self.json_path.exists():
            build_and_save_catalog(DEFAULT_PDF_PATH, self.json_path)

        with open(self.json_path, "r", encoding="utf-8") as f:
            records = json.load(f)

        with conn:
            for r in records:
                conn.execute(
                    """
                    INSERT INTO commands (
                        id, name, clean_name, category, shell, description,
                        examples, risk_level, requires_admin, destructive,
                        template, intents, extra_info
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        r["id"],
                        r["command"],
                        r["clean_name"],
                        r["category"],
                        r["shell"],
                        r["description"],
                        json.dumps(r.get("examples", [])),
                        r["risk_level"],
                        1 if r.get("requires_admin") else 0,
                        1 if r.get("destructive") else 0,
                        r.get("template", ""),
                        json.dumps(r.get("intents", [])),
                        r.get("extra_info", ""),
                    ),
                )

    def _load_cache(self) -> None:
        """Loads all commands into memory for microsecond query lookups."""
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT * FROM commands ORDER BY id ASC;").fetchall()
            self._cache = []
            for row in rows:
                item = dict(row)
                item["examples"] = json.loads(item["examples"])
                item["intents"] = json.loads(item["intents"])
                item["requires_admin"] = bool(item["requires_admin"])
                item["destructive"] = bool(item["destructive"])
                self._cache.append(item)
        finally:
            conn.close()

    def get_all(self) -> list[dict[str, Any]]:
        """Returns all 492 commands."""
        return list(self._cache)

    def get_by_id(self, cmd_id: int) -> Optional[dict[str, Any]]:
        """Retrieves a command by its numeric ID (1-492)."""
        for c in self._cache:
            if c["id"] == cmd_id:
                return c
        return None

    def get_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """Finds a command by exact or clean name (case-insensitive)."""
        target = name.strip().lower()
        for c in self._cache:
            if c["clean_name"].lower() == target or c["name"].lower() == target:
                return c
        return None

    def get_by_category(self, category: str) -> list[dict[str, Any]]:
        """Filters commands by category."""
        target = category.strip().lower()
        return [c for c in self._cache if target in c["category"].lower()]

    def get_by_risk(self, risk_level: str) -> list[dict[str, Any]]:
        """Filters commands by risk level (LOW, MEDIUM, HIGH, CRITICAL)."""
        target = risk_level.strip().upper()
        return [c for c in self._cache if c["risk_level"] == target]

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Fuzzy and keyword search across command names, descriptions, and natural intents."""
        q = (query or "").strip().lower()
        if not q:
            return self._cache[:limit]

        exact = self.get_by_name(q)
        results: list[tuple[float, dict[str, Any]]] = []
        seen_ids = set()

        if exact:
            results.append((100.0, exact))
            seen_ids.add(exact["id"])

        q_words = re.findall(r"[a-zA-Z]+", q)
        q_alpha = " ".join(q_words)

        for cmd in self._cache:
            if cmd["id"] in seen_ids:
                continue

            # Check exact substring containment
            name_lower = cmd["clean_name"].lower()
            desc_lower = cmd["description"].lower()
            intents = [i.lower() for i in cmd.get("intents", [])]

            score = 0.0
            if q == name_lower:
                score = 100.0
            elif q in name_lower:
                score = 90.0
            elif any(q in intent for intent in intents):
                score = 85.0
            elif q in desc_lower:
                score = 75.0
            else:
                # Fuzzy ratio and token set matching against name and intents
                ratio_name = fuzz.partial_ratio(q, name_lower)
                best_intent_token = max([fuzz.token_set_ratio(q, intent) for intent in intents], default=0.0)
                if q_alpha:
                    alpha_intent = max([fuzz.token_set_ratio(q_alpha, intent) for intent in intents], default=0.0)
                    best_intent_token = max(best_intent_token, alpha_intent)

                desc_ratio = fuzz.partial_ratio(q, desc_lower)
                score = max(ratio_name * 0.9, best_intent_token, desc_ratio * 0.7)

            if score >= 45.0:
                results.append((score, cmd))
                seen_ids.add(cmd["id"])

        results.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in results[:limit]]


_db_instance: Optional[CommandDatabase] = None


def get_command_db() -> CommandDatabase:
    """Returns the singleton CommandDatabase instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = CommandDatabase()
    return _db_instance
