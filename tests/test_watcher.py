"""Tests for Proactive Desktop Background Watcher."""

import time
from unittest.mock import MagicMock, patch

import pytest

from voice.watcher import SystemAlert, SystemWatcher


def test_system_alert_dataclass():
    alert = SystemAlert(
        alert_type="HIGH_RAM",
        title="High Memory Usage",
        message="System RAM is at 92.5%",
        spoken_text="Pardon the interruption, Sir: memory is at 92 percent.",
        metric_value=92.5,
        threshold=90.0,
        severity="warning",
    )
    assert alert.alert_type == "HIGH_RAM"
    assert alert.metric_value == 92.5
    assert alert.severity == "warning"


def test_watcher_start_stop_lifecycle():
    watcher = SystemWatcher()
    assert not watcher.is_running

    watcher.start()
    assert watcher.is_running

    watcher.stop()
    assert not watcher.is_running


def test_watcher_high_ram_detection():
    watcher = SystemWatcher()

    mock_mem = MagicMock()
    mock_mem.percent = 93.0
    mock_mem.used = 14 * 1024**3
    mock_mem.total = 16 * 1024**3

    with patch("psutil.virtual_memory", return_value=mock_mem), \
         patch("psutil.disk_usage", return_value=MagicMock(free=50 * 1024**3)), \
         patch("psutil.cpu_percent", return_value=25.0), \
         patch("psutil.sensors_battery", return_value=None):

        alerts = watcher.check_metrics()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "HIGH_RAM"
        assert alerts[0].metric_value == 93.0
        assert "93 percent" in alerts[0].spoken_text

        # Test cooldown debouncing: immediate second check should return nothing
        second_alerts = watcher.check_metrics()
        assert len(second_alerts) == 0


def test_watcher_low_disk_detection():
    watcher = SystemWatcher()

    mock_disk = MagicMock()
    mock_disk.free = 7.5 * 1024**3  # 7.5 GB free (< 10GB threshold)

    with patch("psutil.virtual_memory", return_value=MagicMock(percent=50.0)), \
         patch("psutil.disk_usage", return_value=mock_disk), \
         patch("psutil.cpu_percent", return_value=15.0), \
         patch("psutil.sensors_battery", return_value=None):

        alerts = watcher.check_metrics()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "LOW_DISK"
        assert alerts[0].metric_value == 7.5
        assert "7.5 gigabytes" in alerts[0].spoken_text


def test_watcher_sustained_cpu_detection():
    watcher = SystemWatcher()

    with patch("psutil.virtual_memory", return_value=MagicMock(percent=50.0)), \
         patch("psutil.disk_usage", return_value=MagicMock(free=50 * 1024**3)), \
         patch("psutil.cpu_percent", return_value=98.0), \
         patch("psutil.sensors_battery", return_value=None):

        # First check: consecutive high = 1 (should NOT alert to prevent burst false positives)
        first_alerts = watcher.check_metrics()
        assert len(first_alerts) == 0

        # Second check: consecutive high = 2 (triggers alert!)
        second_alerts = watcher.check_metrics()
        assert len(second_alerts) == 1
        assert second_alerts[0].alert_type == "HIGH_CPU"
        assert second_alerts[0].metric_value == 98.0


def test_watcher_critical_battery_detection():
    watcher = SystemWatcher()

    mock_batt = MagicMock()
    mock_batt.percent = 12
    mock_batt.power_plugged = False

    with patch("psutil.virtual_memory", return_value=MagicMock(percent=50.0)), \
         patch("psutil.disk_usage", return_value=MagicMock(free=50 * 1024**3)), \
         patch("psutil.cpu_percent", return_value=15.0), \
         patch("psutil.sensors_battery", return_value=mock_batt):

        alerts = watcher.check_metrics()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "LOW_BATTERY"
        assert alerts[0].metric_value == 12.0
        assert "battery reserve is at 12 percent" in alerts[0].spoken_text
