"""Fuzzy application search over the app database, backed by RapidFuzz."""

from __future__ import annotations

from rapidfuzz import fuzz, process

import config
from scanner.app_scanner import load_database, rescan
from scanner.models import AppEntry

# When several unrelated apps happen to share the exact same alias (e.g. a
# raw "WinRAR" folder name attached to Rar.exe, RarExtInstaller.exe, and the
# real WinRAR shortcut), prefer the source that represents a deliberate,
# user-facing launch point over one found by crawling directories.
_SOURCE_PRIORITY = {
    "start_menu": 0,
    "registry_app_paths": 1,
    "windows_apps": 1,
    "desktop": 2,
    "registry_uninstall": 3,
    "program_files": 4,
    "path": 5,
    "windows_apps_folder": 6,
}

# Shortcuts for auxiliary material (help files, uninstallers, changelogs...)
# that shouldn't win a tie against the actual application shortcut.
_SECONDARY_NAME_WORDS = (
    "help", "readme", "uninstall", "release notes", "documentation",
    "settings", "configuration", "diagnostics", "manual", "changelog",
    "license", "website",
)


class AppIndex:
    """In-memory, fuzzy-searchable index over the discovered applications."""

    def __init__(self, apps: list[AppEntry] | None = None) -> None:
        """If `apps` is given, indexes it directly instead of touching disk
        (used by tests). Otherwise loads the on-disk database, scanning the
        system first if no cache exists yet."""
        self._apps: list[AppEntry] = []
        self._alias_pairs: list[tuple[str, int]] = []  # (alias, index into _apps)
        if apps is not None:
            self._set_apps(apps)
        else:
            self.load()

    def load(self) -> None:
        apps = load_database()
        if apps is None:
            apps = rescan(verbose=True)
        self._set_apps(apps)

    def reload(self, apps: list[AppEntry] | None = None) -> None:
        """Rebuilds the index, either from a freshly-scanned list or from disk."""
        self._set_apps(apps if apps is not None else (load_database() or []))

    def _set_apps(self, apps: list[AppEntry]) -> None:
        self._apps = apps
        self._alias_pairs = [
            (alias, i) for i, app in enumerate(apps) for alias in app.aliases
        ]

    def __len__(self) -> int:
        return len(self._apps)

    @property
    def apps(self) -> list[AppEntry]:
        return self._apps

    def _rank(self, app: AppEntry, query: str) -> tuple[int, int, int, int]:
        lower_name = app.name.strip().lower()
        is_secondary = any(word in lower_name for word in _SECONDARY_NAME_WORDS)
        return (
            0 if lower_name == query else 1,
            1 if is_secondary else 0,
            _SOURCE_PRIORITY.get(app.source, 9),
            len(app.name),
        )

    def find(self, query: str) -> AppEntry | None:
        """Returns the best-matching app for a free-text query, or None."""
        if not query or not self._alias_pairs:
            return None

        query = query.strip().lower()

        # Exact alias hits short-circuit the fuzzy search. Several apps can
        # share the same exact alias, so rank the ties instead of taking
        # whichever happened to be scanned first.
        exact_hits = [self._apps[i] for alias, i in self._alias_pairs if alias == query]
        if exact_hits:
            return min(exact_hits, key=lambda app: self._rank(app, query))

        choices = [alias for alias, _ in self._alias_pairs]
        matches = process.extract(
            query, choices, scorer=fuzz.token_set_ratio,
            score_cutoff=config.APP_SEARCH_CUTOFF, limit=10,
        )
        if not matches:
            return None

        top_score = matches[0][1]
        candidates = [
            self._apps[self._alias_pairs[choice_index][1]]
            for _, score, choice_index in matches
            if score == top_score
        ]
        return min(candidates, key=lambda app: self._rank(app, query))

    def find_many(self, query: str, limit: int = 5) -> list[AppEntry]:
        """Returns up to `limit` distinct candidate apps, best match first."""
        if not query or not self._alias_pairs:
            return []

        query = query.strip().lower()
        choices = [alias for alias, _ in self._alias_pairs]
        matches = process.extract(
            query, choices, scorer=fuzz.token_set_ratio,
            score_cutoff=config.APP_SEARCH_CUTOFF, limit=limit * 3,
        )

        seen: set[int] = set()
        results: list[AppEntry] = []
        for _, _, choice_index in matches:
            _, app_index = self._alias_pairs[choice_index]
            if app_index in seen:
                continue
            seen.add(app_index)
            results.append(self._apps[app_index])
            if len(results) >= limit:
                break
        return results


_index: AppIndex | None = None


def get_index() -> AppIndex:
    """Returns the process-wide singleton AppIndex, building it on first use."""
    global _index
    if _index is None:
        _index = AppIndex()
    return _index


def refresh_index() -> int:
    """Rescans the whole system and rebuilds the singleton index in place."""
    apps = rescan(verbose=False)
    get_index().reload(apps)
    return len(apps)
