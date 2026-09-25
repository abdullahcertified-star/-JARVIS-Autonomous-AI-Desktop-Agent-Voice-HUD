"""Tests for actions/context.py and agent ambient context integration."""

from unittest.mock import MagicMock, patch
import pytest

from dispatcher import dispatch
from actions import context
import agent


def test_presence_state_classification():
    with patch("actions.context.get_idle_seconds", return_value=15.0):
        st = context.get_presence_state()
        assert st["state"] == "active"
        assert st["idle_seconds"] == 15.0

    with patch("actions.context.get_idle_seconds", return_value=120.0):
        st = context.get_presence_state()
        assert st["state"] == "idle"

    with patch("actions.context.get_idle_seconds", return_value=500.0):
        st = context.get_presence_state()
        assert st["state"] == "away"


def test_focus_mode_lifecycle():
    # 1. Enable focus
    res1 = dispatch({
        "action": "context",
        "operation": "enable_focus",
        "goal": "Deep Code Refactor",
    })
    assert res1["success"] is True
    assert res1["focus_active"] is True
    assert "Deep Code Refactor" in res1["message"]

    # 2. Check focus status
    status_res = dispatch({
        "action": "context",
        "operation": "get_focus_status",
    })
    assert status_res["success"] is True
    assert status_res["focus_active"] is True
    assert "Deep Code Refactor" in status_res["message"]

    # 3. Test alert suppression: warnings suppressed, critical alerts pass
    assert context.should_suppress_alert(severity="warning") is True
    assert context.should_suppress_alert(severity="critical") is False

    # 4. Disable focus
    res2 = dispatch({
        "action": "context",
        "operation": "disable_focus",
    })
    assert res2["success"] is True
    assert res2["focus_active"] is False
    assert "deactivated" in res2["message"]

    # 5. Alert suppression now inactive
    with patch("actions.context.is_quiet_hours", return_value=False):
        assert context.should_suppress_alert(severity="warning") is False


def test_quiet_hours_evaluation():
    # Configure 23:00 to 07:00
    with patch.object(context, "_quiet_hours_enabled", True), \
         patch.object(context, "_quiet_hours_start_hour", 23), \
         patch.object(context, "_quiet_hours_end_hour", 7):

        mock_dt = MagicMock()
        mock_dt.now.return_value.hour = 23
        with patch("actions.context.datetime.datetime", mock_dt):
            assert context.is_quiet_hours() is True

        mock_dt.now.return_value.hour = 3
        with patch("actions.context.datetime.datetime", mock_dt):
            assert context.is_quiet_hours() is True

        mock_dt.now.return_value.hour = 14
        with patch("actions.context.datetime.datetime", mock_dt):
            assert context.is_quiet_hours() is False


def test_set_quiet_hours():
    res = dispatch({
        "action": "context",
        "operation": "set_quiet_hours",
        "start_hour": 22,
        "end_hour": 6,
        "enabled": True,
    })
    assert res["success"] is True
    assert res["start"] == 22
    assert res["end"] == 6


def test_get_ambient_context():
    res = dispatch({
        "action": "context",
        "operation": "get_ambient_context",
    })
    assert res["success"] is True
    assert "Ambient Context" in res["message"]
    assert "presence" in res
    assert "focus_active" in res


def test_agent_context_tools():
    with patch("agent.dispatch") as mock_dispatch:
        mock_dispatch.return_value = {"success": True, "message": "Focus Mode is now active"}
        res1 = agent.set_focus_mode(True, "Working")
        assert "Focus Mode is now active" in res1

        mock_dispatch.return_value = {"success": True, "message": "Focus Mode is active (10m elapsed)"}
        res2 = agent.get_focus_status()
        assert "Focus Mode is active" in res2

        mock_dispatch.return_value = {"success": True, "message": "Presence: active"}
        res3 = agent.get_user_presence()
        assert "Presence: active" in res3

        mock_dispatch.return_value = {"success": True, "message": "Ambient Context: OK"}
        res4 = agent.get_ambient_context()
        assert "Ambient Context: OK" in res4


def test_fast_path_ambient_context():
    with patch("agent.set_focus_mode", return_value="Sir, Focus Mode enabled.") as mock_focus, \
         patch("agent.get_focus_status", return_value="Sir, 15m elapsed.") as mock_fstatus, \
         patch("agent.get_user_presence", return_value="Sir, user active.") as mock_pres, \
         patch("agent.get_ambient_context", return_value="Sir, ambient all green.") as mock_amb:

        res1 = agent.check_fast_path("Jarvis, enter focus mode for ML training")
        assert res1 == "Sir, Focus Mode enabled."
        mock_focus.assert_called_with(True, "ml training")

        res2 = agent.check_fast_path("exit focus mode")
        assert res2 == "Sir, Focus Mode enabled."
        mock_focus.assert_called_with(False)

        res3 = agent.check_fast_path("am I in focus mode")
        assert res3 == "Sir, 15m elapsed."
        mock_fstatus.assert_called_once()

        res4 = agent.check_fast_path("am I idle?")
        assert res4 == "Sir, user active."
        mock_pres.assert_called_once()

        res5 = agent.check_fast_path("Jarvis, ambient context")
        assert res5 == "Sir, ambient all green."
        mock_amb.assert_called_once()
