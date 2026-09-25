"""Unit tests for actions.system: set_volume (mocked -- must not actually
change the machine's real volume on every test run) and run_command (real,
since running 'echo' has no lasting side effect worth mocking around).
"""

from __future__ import annotations

from typing import Any

import pytest

from actions import system as system_actions


class _FakeVolumeEndpoint:
    def __init__(self) -> None:
        self.scalar = 0.7
        self.set_calls: list[float] = []

    def SetMasterVolumeLevelScalar(self, value: float, _guid: Any) -> None:
        self.set_calls.append(value)
        self.scalar = value

    def GetMasterVolumeLevelScalar(self) -> float:
        return self.scalar

    def GetMute(self) -> int:
        return 0


@pytest.fixture
def fake_volume(monkeypatch) -> _FakeVolumeEndpoint:
    endpoint = _FakeVolumeEndpoint()
    monkeypatch.setattr(system_actions, "_get_volume_endpoint", lambda: endpoint)
    return endpoint


def test_set_volume_calls_pycaw_with_scaled_value(fake_volume) -> None:
    result = system_actions.system_action({"operation": "set_volume", "level": 50})
    assert result["success"] is True
    assert result["level"] == 50
    assert fake_volume.set_calls == [0.5]


def test_set_volume_requires_level(fake_volume) -> None:
    result = system_actions.system_action({"operation": "set_volume"})
    assert result["success"] is False


def test_set_volume_rejects_out_of_range(fake_volume) -> None:
    result = system_actions.system_action({"operation": "set_volume", "level": 150})
    assert result["success"] is False
    assert fake_volume.set_calls == []


def test_set_volume_rejects_non_numeric(fake_volume) -> None:
    result = system_actions.system_action({"operation": "set_volume", "level": "loud"})
    assert result["success"] is False
    assert fake_volume.set_calls == []


def test_status_reports_volume(fake_volume) -> None:
    result = system_actions.system_action({"operation": "status"})
    assert result["success"] is True
    assert result["volume_percent"] == 70
    assert result["muted"] is False


def test_run_command_returns_stdout() -> None:
    result = system_actions.system_action({"operation": "run_command", "command": "echo hello-jarvis"})
    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "hello-jarvis" in result["stdout"]


def test_run_command_reports_nonzero_exit_as_failure() -> None:
    result = system_actions.system_action({"operation": "run_command", "command": "exit 3"})
    assert result["success"] is False
    assert result["exit_code"] == 3


def test_run_command_requires_command() -> None:
    result = system_actions.system_action({"operation": "run_command"})
    assert result["success"] is False


def test_run_command_times_out() -> None:
    result = system_actions.system_action(
        {"operation": "run_command", "command": "ping -n 10 127.0.0.1 > nul", "timeout": 1}
    )
    assert result["success"] is False
    assert "timed out" in result["message"]
