"""Tests for actions.news.get_news -- real HTTP calls to Google News' free
RSS feed (no API key), since this project favors verifying against the
actual external behavior over mocking it away.
"""

from __future__ import annotations

from actions.news import get_news


def test_get_news_returns_real_headlines() -> None:
    result = get_news({})
    assert result["success"] is True
    assert len(result["headlines"]) > 0
    assert all(isinstance(h, str) and h for h in result["headlines"])


def test_get_news_respects_limit() -> None:
    result = get_news({"limit": 2})
    assert result["success"] is True
    assert len(result["headlines"]) <= 2


def test_get_news_with_topic() -> None:
    result = get_news({"topic": "technology"})
    assert result["success"] is True
    assert result["topic"] == "technology"
    assert len(result["headlines"]) > 0


def test_get_news_rejects_non_numeric_limit() -> None:
    result = get_news({"limit": "not-a-number"})
    assert result["success"] is False
