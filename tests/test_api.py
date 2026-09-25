"""Flask test-client coverage for /execute: request validation plus a few
real action smoke tests (clipboard round-trip, screenshot capture).

These exercise the actual local machine (this project is a Windows desktop
automation server, not something meant to run in a generic sandboxed CI),
so keep destructive actions (shutdown/restart) out of this file.
"""

from __future__ import annotations

import os

import pytest

from app import app as flask_app
from search.app_search import get_index


@pytest.fixture
def client():
    flask_app.config.update(TESTING=True)
    return flask_app.test_client()


def test_health_check(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "JARVIS Desktop API Running"
    assert body["applications_indexed"] == len(get_index())


def test_execute_requires_json_body(client) -> None:
    response = client.post("/execute", data="not json", content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_execute_rejects_unknown_action(client) -> None:
    response = client.post("/execute", json={"action": "nonexistent_action"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is False
    assert "Unknown action" in body["message"]


def test_execute_rejects_missing_required_field(client) -> None:
    response = client.post("/execute", json={"action": "open_url"})
    body = response.get_json()
    assert body["success"] is False
    assert "url" in body["message"]


def test_execute_open_app_requires_a_target(client) -> None:
    response = client.post("/execute", json={"action": "open_app"})
    body = response.get_json()
    assert body["success"] is False
    assert "No application specified" in body["message"]


def test_execute_open_app_accepts_app_alias_field(client) -> None:
    # actions.apps.open_app accepts "target"/"app"/"app_name" interchangeably --
    # this is the exact field name n8n's Open Application tool sends.
    response = client.post(
        "/execute", json={"action": "open_app", "app": "definitely-not-a-real-app-xyz"}
    )
    body = response.get_json()
    # Still "not found" for a bogus name, but critically NOT a validation
    # error about a missing field -- proves the "app" alias was accepted.
    assert body["success"] is False
    assert "not installed" in body["message"] or "could not be found" in body["message"]


def test_execute_search_youtube_requires_query(client) -> None:
    response = client.post("/execute", json={"action": "search_youtube"})
    body = response.get_json()
    assert body["success"] is False
    assert "query" in body["message"]


def test_execute_open_app_not_found(client) -> None:
    response = client.post(
        "/execute", json={"action": "open_app", "target": "definitely-not-a-real-app-xyz"}
    )
    body = response.get_json()
    assert body["success"] is False


def test_execute_clipboard_roundtrip(client) -> None:
    write = client.post("/execute", json={"action": "clipboard", "operation": "copy", "text": "jarvis-test-123"})
    assert write.get_json()["success"] is True

    read = client.post("/execute", json={"action": "clipboard", "operation": "paste"})
    body = read.get_json()
    assert body["success"] is True
    assert body["content"] == "jarvis-test-123"


def test_execute_screenshot_capture(client, monkeypatch) -> None:
    from PIL import Image

    monkeypatch.setattr("actions.screenshot.capture_image", lambda region=None: Image.new("RGB", (10, 10), color="blue"))
    response = client.post("/execute", json={"action": "screenshot", "operation": "capture"})
    body = response.get_json()
    assert body["success"] is True
    assert os.path.isfile(body["path"])
    os.remove(body["path"])


def test_execute_unknown_operation_within_known_action(client) -> None:
    response = client.post("/execute", json={"action": "mouse", "operation": "teleport"})
    body = response.get_json()
    assert body["success"] is False
    assert "Unknown mouse operation" in body["message"]
