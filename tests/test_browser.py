"""Unit tests for actions.browser's browser-targeting logic.

These monkeypatch os.startfile / webbrowser.open / the app index instead of
actually launching browsers -- the point is to verify which code path gets
taken, not to pop open real windows on every test run (screenshot/clipboard
in test_api.py already cover "does a real side effect happen" territory).
"""

from __future__ import annotations

from typing import Any

import pytest

from actions import browser as browser_actions
from scanner.models import AppEntry


class _FakeIndex:
    def __init__(self, result: AppEntry | None) -> None:
        self._result = result

    def find(self, _query: str) -> AppEntry | None:
        return self._result


@pytest.fixture
def calls() -> dict[str, Any]:
    return {"startfile": None, "webopen": None}


def _patch_common(monkeypatch, calls, index_result: AppEntry | None) -> None:
    monkeypatch.setattr(browser_actions, "get_index", lambda: _FakeIndex(index_result))
    monkeypatch.setattr(
        browser_actions.os, "startfile",
        lambda path, arguments="": calls.__setitem__("startfile", (path, arguments)),
    )
    monkeypatch.setattr(
        browser_actions.webbrowser, "open",
        lambda url: calls.__setitem__("webopen", url),
    )


def test_no_browser_requested_uses_default(monkeypatch, calls) -> None:
    _patch_common(monkeypatch, calls, index_result=None)
    note = browser_actions._open_in_browser("https://example.com", None)
    assert note == ""
    assert calls["webopen"] == "https://example.com"
    assert calls["startfile"] is None


def test_browser_found_and_launchable_uses_startfile(monkeypatch, calls) -> None:
    edge = AppEntry(name="Microsoft Edge", path=r"C:\Edge\msedge.exe", kind="exe", source="start_menu")
    _patch_common(monkeypatch, calls, index_result=edge)

    note = browser_actions._open_in_browser("https://youtube.com/results?search_query=x", "edge")

    assert "Microsoft Edge" in note
    assert calls["startfile"] == (r"C:\Edge\msedge.exe", "https://youtube.com/results?search_query=x")
    assert calls["webopen"] is None


def test_browser_not_found_falls_back_to_default(monkeypatch, calls) -> None:
    _patch_common(monkeypatch, calls, index_result=None)
    note = browser_actions._open_in_browser("https://example.com", "some-nonexistent-browser")

    assert "not found" in note
    assert calls["webopen"] == "https://example.com"
    assert calls["startfile"] is None


def test_browser_found_but_not_argv_launchable_falls_back(monkeypatch, calls) -> None:
    store_app = AppEntry(name="Weather", path="Microsoft.BingWeather!App", kind="uwp", source="windows_apps")
    _patch_common(monkeypatch, calls, index_result=store_app)

    note = browser_actions._open_in_browser("https://example.com", "weather")

    assert "couldn't target" in note
    assert calls["webopen"] == "https://example.com"
    assert calls["startfile"] is None


def test_search_youtube_builds_correct_url(monkeypatch, calls) -> None:
    _patch_common(monkeypatch, calls, index_result=None)
    result = browser_actions.search_youtube({"query": "lofi beats"})

    assert result["success"] is True
    assert calls["webopen"] == "https://www.youtube.com/results?search_query=lofi%20beats"


def test_search_youtube_requires_query() -> None:
    result = browser_actions.search_youtube({})
    assert result["success"] is False
