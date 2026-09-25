"""Tests for Interactive HUD Risk Confirmation Modal and Resolution."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from actions.command import _execute
from commands.safety import RiskLevel
from voice.main import _handle_voice_confirmation
from voice.ui import JarvisWindow, get_active_window


def test_jarvis_window_confirmation_approval():
    # Mock webview window
    mock_wv = MagicMock()
    with patch("voice.ui.webview.create_window", return_value=mock_wv), \
         patch("voice.ui._start_static_server", return_value=8080):
        win = JarvisWindow()

        # Simulate background worker approving the confirmation
        def _approver():
            time.sleep(0.05)
            assert win.has_pending_confirmation()
            assert win.resolve_active_confirmation(True) is True

        t = threading.Thread(target=_approver)
        t.start()

        approved = win.wait_for_confirmation(
            command="taskkill /PID 1234 /F",
            shell="cmd",
            risk_level="HIGH",
            reason="Terminate process",
            timeout_seconds=2,
        )
        t.join()

        assert approved is True
        assert not win.has_pending_confirmation()
        # Verify evaluate_js was called to show and hide
        assert mock_wv.evaluate_js.called


def test_jarvis_window_confirmation_denial():
    mock_wv = MagicMock()
    with patch("voice.ui.webview.create_window", return_value=mock_wv), \
         patch("voice.ui._start_static_server", return_value=8080):
        win = JarvisWindow()

        def _denier():
            time.sleep(0.05)
            assert win.has_pending_confirmation()
            assert win.resolve_active_confirmation(False) is True

        t = threading.Thread(target=_denier)
        t.start()

        approved = win.wait_for_confirmation(
            command="format D:",
            shell="cmd",
            risk_level="CRITICAL",
            reason="Format disk",
            timeout_seconds=2,
        )
        t.join()

        assert approved is False
        assert not win.has_pending_confirmation()


def test_handle_voice_confirmation_affirmative_and_negative():
    mock_win = MagicMock()
    mock_win.has_pending_confirmation.return_value = True

    # Affirmative words
    assert _handle_voice_confirmation("yes", mock_win) is True
    mock_win.resolve_active_confirmation.assert_called_with(True)

    assert _handle_voice_confirmation("proceed with execution", mock_win) is True
    mock_win.resolve_active_confirmation.assert_called_with(True)

    assert _handle_voice_confirmation("confirm", mock_win) is True
    mock_win.resolve_active_confirmation.assert_called_with(True)

    # Negative words
    assert _handle_voice_confirmation("no", mock_win) is True
    mock_win.resolve_active_confirmation.assert_called_with(False)

    assert _handle_voice_confirmation("cancel that", mock_win) is True
    mock_win.resolve_active_confirmation.assert_called_with(False)


def test_execute_with_active_window_approval():
    mock_win = MagicMock()
    mock_win.wait_for_confirmation.return_value = True

    with patch("voice.ui.get_active_window", return_value=mock_win), \
         patch("commands.executor.CommandExecutor.execute") as mock_cmd_exec:
        mock_cmd_exec.return_value = {
            "success": True,
            "exit_code": 0,
            "stdout": "SUCCESS: The process with PID 9999 has been terminated.",
            "stderr": "",
            "duration_ms": 10.0,
        }

        # Request to kill PID requires confirmation
        res = _execute({"request": "kill process 9999", "confirmed": False})
        assert mock_win.wait_for_confirmation.called
        assert res.get("success") is True


def test_execute_with_active_window_denial():
    mock_win = MagicMock()
    mock_win.wait_for_confirmation.return_value = False

    with patch("voice.ui.get_active_window", return_value=mock_win), \
         patch("commands.executor.CommandExecutor.execute") as mock_cmd_exec:
        res = _execute({"request": "kill process 9999", "confirmed": False})
        assert mock_win.wait_for_confirmation.called
        assert res.get("success") is False
        assert not mock_cmd_exec.called
