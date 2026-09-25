"""get_news: fetches real headline text via Google News' free RSS feed.

Unlike search_google, this doesn't just open a browser tab -- it actually
retrieves headline content so the AI agent can read it back to the user.
No API key or signup needed.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import requests

from dispatcher import register
from utils.helpers import fail, ok

_FEED_BASE = "https://news.google.com/rss"
_DEFAULT_LIMIT = 5
_MAX_LIMIT = 15
_REQUEST_TIMEOUT = 10


@register("get_news")
def get_news(data: dict[str, Any]) -> dict[str, Any]:
    topic = (data.get("topic") or data.get("query") or "").strip()

    try:
        limit = int(data.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return fail("'limit' must be a whole number")
    limit = max(1, min(limit, _MAX_LIMIT))

    if topic:
        url = f"{_FEED_BASE}/search?q={urllib.parse.quote(topic)}&hl=en-US&gl=US&ceid=US:en"
    else:
        url = f"{_FEED_BASE}?hl=en-US&gl=US&ceid=US:en"

    try:
        response = requests.get(url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        return fail(f"Failed to fetch news: {exc}")

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        return fail(f"Failed to parse news feed: {exc}")

    headlines = [
        title.strip()
        for item in root.findall(".//item")[:limit]
        if (title := item.findtext("title", "")) and title.strip()
    ]

    if not headlines:
        subject = f" for '{topic}'" if topic else ""
        return fail(f"No news headlines found{subject}")

    summary = "; ".join(headlines)
    subject = f" about {topic}" if topic else ""
    return ok(f"Latest headlines{subject}: {summary}", headlines=headlines, topic=topic or "general")
