"""Unit tests for search.app_search.AppIndex against a fixed fixture -- no
filesystem/registry scanning involved, so these run fast and deterministically.
"""

from __future__ import annotations

import pytest

from scanner.models import AppEntry
from search.app_search import AppIndex


@pytest.fixture
def index() -> AppIndex:
    apps = [
        AppEntry(
            name="Google Chrome", path=r"C:\Chrome\chrome.exe", kind="exe",
            source="start_menu", aliases={"google chrome", "chrome"},
        ),
        AppEntry(
            name="Microsoft Visual Studio Code", path=r"C:\VSCode\Code.exe", kind="exe",
            source="start_menu", aliases={"microsoft visual studio code", "visual studio code", "code"},
        ),
        AppEntry(
            name="Cisco Packet Tracer", path=r"C:\PT\PacketTracer.exe", kind="exe",
            source="start_menu", aliases={"cisco packet tracer", "packet tracer", "cisco"},
        ),
        AppEntry(
            name="OBS Studio", path=r"C:\OBS\obs64.exe", kind="exe",
            source="start_menu", aliases={"obs studio", "obs"},
        ),
        AppEntry(
            name="WinRAR", path=r"C:\WinRAR\WinRAR.exe", kind="lnk",
            source="start_menu", aliases={"winrar"},
        ),
        AppEntry(
            name="RarExtInstaller", path=r"C:\WinRAR\RarExtInstaller.exe", kind="exe",
            source="program_files", aliases={"rarextinstaller", "winrar"},
        ),
    ]
    return AppIndex(apps=apps)


def test_exact_alias_match(index: AppIndex) -> None:
    match = index.find("chrome")
    assert match is not None
    assert match.name == "Google Chrome"


def test_fuzzy_full_name(index: AppIndex) -> None:
    assert index.find("google chrome").name == "Google Chrome"


def test_fuzzy_abbreviation(index: AppIndex) -> None:
    assert index.find("vs code").name == "Microsoft Visual Studio Code"


def test_multi_word_alias(index: AppIndex) -> None:
    assert index.find("packet tracer").name == "Cisco Packet Tracer"


def test_typo_tolerance(index: AppIndex) -> None:
    assert index.find("crome").name == "Google Chrome"


def test_no_match_returns_none(index: AppIndex) -> None:
    assert index.find("some totally unrelated application xyz") is None


def test_empty_query_returns_none(index: AppIndex) -> None:
    assert index.find("") is None


def test_exact_alias_tie_prefers_start_menu_source(index: AppIndex) -> None:
    # Both WinRAR (start_menu) and RarExtInstaller (program_files) have the
    # exact alias "winrar" -- the deliberate shortcut should win the tie.
    match = index.find("winrar")
    assert match is not None
    assert match.name == "WinRAR"
    assert match.source == "start_menu"


def test_find_many_ranks_best_first(index: AppIndex) -> None:
    results = index.find_many("studio", limit=5)
    names = [r.name for r in results]
    assert "Microsoft Visual Studio Code" in names or "OBS Studio" in names
