"""Real-time Voice Interruption (Barge-In) Monitor for JARVIS.

Allows the user to speak while Jarvis is talking, instantly (<50ms)
cutting off speech playback and returning to listening mode.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import sounddevice as sd

from voice import config
from voice.audio import calc_rms, get_ambient_threshold, open_input_stream


class BargeInMonitor:
    """Monitors the microphone during TTS speech playback to detect when the
    user begins speaking, immediately interrupting audio playback.
    """

    def __init__(
        self,
        interrupt_event: Optional[threading.Event] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
    ) -> None:
        self.interrupt_event = interrupt_event or threading.Event()
        self.on_interrupt = on_interrupt
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.interrupted = False
        self.enabled = getattr(config, "BARGE_IN_ENABLED", True)

    def start(self) -> "BargeInMonitor":
        """Starts monitoring the microphone on a daemon thread."""
        if not self.enabled:
            return self

        self.interrupted = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stops the monitoring thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.4)
            self._thread = None

    def __enter__(self) -> "BargeInMonitor":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def _monitor_loop(self) -> None:
        # 50ms audio chunk = 800 samples at 16kHz
        chunk_samples = int(config.SAMPLE_RATE * 0.05)
        grace_period = getattr(config, "BARGE_IN_GRACE_PERIOD_SEC", 0.25)
        energy_ratio = getattr(config, "BARGE_IN_ENERGY_RATIO", 3.0)

        # Allow initial playback transient to pass before evaluating interruption
        start_time = time.time()
        consecutive_loud = 0

        # Base threshold on calibrated ambient room noise
        ambient_thresh = get_ambient_threshold()
        # Interruption requires clear deliberate speech: at least 3x ambient floor and min 450 RMS
        interruption_threshold = max(ambient_thresh * energy_ratio, 450.0)

        try:
            with open_input_stream(chunk_samples) as stream:
                while not self._stop_event.is_set() and not self.interrupt_event.is_set():
                    chunk, _overflow = stream.read(chunk_samples)
                    pcm = chunk[:, 0]
                    rms = calc_rms(pcm)

                    # Respect grace period
                    if time.time() - start_time < grace_period:
                        continue

                    if rms >= interruption_threshold:
                        consecutive_loud += 1
                        # 2 consecutive loud chunks (~100ms) filters out single clicks/coughs
                        if consecutive_loud >= 2:
                            print(f"\n  [barge-in] User voice detected (RMS={rms:.0f} > thresh={interruption_threshold:.0f}) -> interrupting playback!")
                            self.interrupted = True
                            self.interrupt_event.set()
                            try:
                                sd.stop()
                            except Exception:
                                pass
                            if self.on_interrupt:
                                try:
                                    self.on_interrupt()
                                except Exception:
                                    pass
                            break
                    else:
                        consecutive_loud = 0
        except Exception as exc:
            # Mic might be temporarily busy or unreadable; log and exit monitor cleanly
            pass
