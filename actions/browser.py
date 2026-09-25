"""open_url / search_google / search_youtube: browser-driven actions.

All three accept an optional "browser" field (e.g. "edge", "chrome",
"firefox") to target a specific installed browser instead of the OS
default -- resolved via the same fuzzy app search used by open_app, so no
separate browser registry is needed.
"""

from __future__ import annotations

import os
import urllib.parse
import webbrowser
from typing import Any

from dispatcher import register
from search.app_search import get_index
from utils.helpers import fail, ok

# Kinds the app index can actually launch with a URL argument via
# os.startfile(path, arguments=...). UWP/folder/file entries can't take an
# extra argument this way, so those fall back to the OS default browser.
_ARGV_LAUNCHABLE_KINDS = {"exe", "lnk"}


def _open_in_browser(url: str, browser: str | None) -> str:
    """Opens url, in a specific browser if requested and found. Returns a
    human-readable note about which browser was actually used."""
    if browser:
        app = get_index().find(browser)
        if app and app.kind in _ARGV_LAUNCHABLE_KINDS:
            os.startfile(app.path, arguments=url)  # noqa: S606
            return f" in {app.name}"
        webbrowser.open(url)
        if app:
            return f" (couldn't target {app.name} directly, used your default browser)"
        return f" (browser '{browser}' not found, used your default browser)"

    webbrowser.open(url)
    return ""


@register("open_url")
def open_url(data: dict[str, Any]) -> dict[str, Any]:
    url = (data.get("url") or "").strip()
    if not url:
        return fail("No URL provided")

    if "://" not in url:
        url = f"https://{url}"

    note = _open_in_browser(url, data.get("browser"))
    return ok(f"Opened {url}{note}")


@register("search_google")
def search_google(data: dict[str, Any]) -> dict[str, Any]:
    query = (data.get("query") or "").strip()
    if not query:
        return fail("No search query provided")

    search_url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    note = _open_in_browser(search_url, data.get("browser"))
    return ok(f"Searching Google for {query}{note}")


@register("search_youtube")
def search_youtube(data: dict[str, Any]) -> dict[str, Any]:
    query = (data.get("query") or "").strip()
    if not query:
        return fail("No search query provided")

    search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    note = _open_in_browser(search_url, data.get("browser"))
    return ok(f"Searching YouTube for {query}{note}")
