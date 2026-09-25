"""Proactive Desktop Background Watcher for JARVIS.

Periodically monitors critical system telemetry (RAM overload, disk depletion,
sustained CPU spikes, critical battery) and generates proactive advisory alerts
with intelligent cooldowns and zero-latency debouncing.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import psutil

from voice import config

logger = logging.getLogger("jarvis.watcher")


@dataclass
class SystemAlert:
    """Represents a proactive system health advisory alert."""
    alert_type: str
    title: str
    message: str
    spoken_text: str
    metric_value: float
    threshold: float
    severity: str = "warning"  # "warning" or "critical"


class SystemWatcher:
    """Background monitor checking system resources and dispatching proactive advisories."""

    def __init__(self, on_alert: Optional[Callable[[SystemAlert], None]] = None) -> None:
        self.on_alert = on_alert
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_alert_time: dict[str, float] = {}
        self._consecutive_high_cpu = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def check_metrics(self) -> List[SystemAlert]:
        """Evaluates current system health metrics against configured thresholds."""
        alerts: List[SystemAlert] = []
        now = time.time()
        cooldown = getattr(config, "WATCHER_COOLDOWN_SEC", 300.0)

        # 1. RAM Utilization Check
        ram_thresh = getattr(config, "WATCHER_RAM_THRESHOLD_PERCENT", 90.0)
        try:
            mem = psutil.virtual_memory()
            if mem.percent >= ram_thresh:
                last_time = self._last_alert_time.get("RAM", 0.0)
                if now - last_time >= cooldown:
                    self._last_alert_time["RAM"] = now
                    alerts.append(
                        SystemAlert(
                            alert_type="HIGH_RAM",
                            title="High Memory Usage",
                            message=f"System RAM is at {mem.percent:.1f}% ({mem.used / (1024**3):.1f} GB / {mem.total / (1024**3):.1f} GB)",
                            spoken_text=f"Pardon the interruption, Sir Abdullah: system memory usage has reached {mem.percent:.0f} percent.",
                            metric_value=mem.percent,
                            threshold=ram_thresh,
                            severity="critical" if mem.percent >= 95.0 else "warning",
                        )
                    )
        except Exception as exc:
            logger.debug("Failed to read memory metrics: %s", exc)

        # 2. Disk Space Depletion Check (Primary C: drive)
        disk_min_gb = getattr(config, "WATCHER_DISK_MIN_GB", 10.0)
        try:
            disk = psutil.disk_usage("C:\\")
            free_gb = disk.free / (1024**3)
            if free_gb <= disk_min_gb:
                last_time = self._last_alert_time.get("DISK", 0.0)
                if now - last_time >= cooldown:
                    self._last_alert_time["DISK"] = now
                    alerts.append(
                        SystemAlert(
                            alert_type="LOW_DISK",
                            title="Low Disk Space",
                            message=f"Primary drive (C:) free space is critically low: {free_gb:.1f} GB remaining",
                            spoken_text=f"Advisory notice, Sir: primary drive free space is down to {free_gb:.1f} gigabytes.",
                            metric_value=round(free_gb, 1),
                            threshold=disk_min_gb,
                            severity="critical" if free_gb <= 5.0 else "warning",
                        )
                    )
        except Exception as exc:
            logger.debug("Failed to read disk metrics: %s", exc)

        # 3. Sustained CPU Overload Check
        cpu_thresh = getattr(config, "WATCHER_CPU_THRESHOLD_PERCENT", 95.0)
        try:
            cpu = psutil.cpu_percent(interval=None)
            if cpu >= cpu_thresh:
                self._consecutive_high_cpu += 1
                if self._consecutive_high_cpu >= 2:
                    last_time = self._last_alert_time.get("CPU", 0.0)
                    if now - last_time >= cooldown:
                        self._last_alert_time["CPU"] = now
                        alerts.append(
                            SystemAlert(
                                alert_type="HIGH_CPU",
                                title="Sustained High CPU",
                                message=f"CPU utilization sustained at {cpu:.1f}% across consecutive checks",
                                spoken_text=f"Advisory notice, Sir: CPU utilization is sustained at {cpu:.0f} percent.",
                                metric_value=cpu,
                                threshold=cpu_thresh,
                                severity="warning",
                            )
                        )
            else:
                self._consecutive_high_cpu = 0
        except Exception as exc:
            logger.debug("Failed to read CPU metrics: %s", exc)

        # 4. Critical Battery Check
        battery_min = getattr(config, "WATCHER_BATTERY_MIN_PERCENT", 15.0)
        try:
            batt = psutil.sensors_battery()
            if batt is not None and not batt.power_plugged and batt.percent <= battery_min:
                last_time = self._last_alert_time.get("BATTERY", 0.0)
                if now - last_time >= cooldown:
                    self._last_alert_time["BATTERY"] = now
                    alerts.append(
                        SystemAlert(
                            alert_type="LOW_BATTERY",
                            title="Critical Battery Level",
                            message=f"Battery is at {batt.percent:.0f}% and currently discharging",
                            spoken_text=f"Pardon the interruption, Sir: battery reserve is at {batt.percent:.0f} percent. Please connect to AC power.",
                            metric_value=float(batt.percent),
                            threshold=battery_min,
                            severity="critical",
                        )
                    )
        except Exception as exc:
            logger.debug("Failed to read battery metrics: %s", exc)

        return alerts

    def start(self) -> "SystemWatcher":
        """Starts the watcher daemon thread."""
        if not getattr(config, "WATCHER_ENABLED", True):
            return self

        if self.is_running:
            return self

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="JarvisSystemWatcher")
        self._thread.start()
        logger.info("Jarvis System Watcher started.")
        return self

    def stop(self) -> None:
        """Stops the watcher daemon thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
        logger.info("Jarvis System Watcher stopped.")

    def _run_loop(self) -> None:
        interval = max(5.0, getattr(config, "WATCHER_CHECK_INTERVAL_SEC", 30.0))
        # Initial wait to let machine boot and settle
        if self._stop_event.wait(timeout=5.0):
            return

        while not self._stop_event.is_set():
            try:
                alerts = self.check_metrics()
                for alert in alerts:
                    try:
                        from actions.context import should_suppress_alert
                        if should_suppress_alert(alert.severity):
                            logger.info("Alert %s suppressed due to active Focus Mode or Quiet Hours.", alert.alert_type)
                            continue
                    except Exception:
                        pass

                    if self.on_alert:
                        try:
                            self.on_alert(alert)
                        except Exception as exc:
                            logger.error("Error invoking alert handler: %s", exc)

            except Exception as exc:
                logger.error("Unexpected error in SystemWatcher loop: %s", exc)

            if self._stop_event.wait(timeout=interval):
                break
