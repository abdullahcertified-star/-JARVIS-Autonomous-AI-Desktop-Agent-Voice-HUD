"""Unit tests for actions.apps.open_app's file-path fallback.

Real desktop apps and the app database itself are already covered by
search/test_search.py; this focuses on the specific gap that let
"open page.txt on desktop" fail even though the file genuinely exists --
open_app was only ever trying to fuzzy-match installed applications.
"""

from __future__ import annotations

import os
import tempfile

from actions.apps import open_app


def test_open_app_opens_an_existing_file_directly(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda path: calls.append(path))

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"hello")
        path = f.name

    try:
        result = open_app({"target": path})
        assert result["success"] is True
        assert calls == [path]
    finally:
        os.remove(path)


def test_open_app_resolves_guessed_username_desktop_file(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda path: calls.append(path))

    real_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    filename = "jarvis_test_open_app_file.txt"
    real_path = os.path.join(real_desktop, filename)
    with open(real_path, "w") as f:
        f.write("hello")

    try:
        guessed_path = os.path.join(r"C:\Users\User\Desktop", filename)
        result = open_app({"target": guessed_path})
        assert result["success"] is True
        assert calls == [real_path]
    finally:
        os.remove(real_path)


def test_open_app_falls_back_to_app_search_when_not_a_real_path() -> None:
    # A target that isn't an existing file/folder should still go through
    # the normal fuzzy app search, not be treated as a broken file path.
    result = open_app({"target": "definitely-not-a-real-app-or-file-xyz"})
    assert result["success"] is False
    assert "not installed" in result["message"] or "could not be found" in result["message"]
