"""Real-time Voice Interruption (Barge-In) Monitor for JARVIS.

Allows the user to speak while Jarvis is talking, instantly (<50ms)
cutting off speech playback, capturing the user's interruption utterance,
and immediately returning to active processing.
"""

from __future__ import annotations

from collections import deque
import logging
import threading
import time
from typing import Callable, Optional, Tuple

import numpy as np
import sounddevice as sd

from voice import config
from voice.audio import open_input_stream
from voice.vad import SileroVAD

logger = logging.getLogger("jarvis.barge_in")


class BargeInMonitor:
    """Monitors the microphone concurrently during TTS speech playback.
    When genuine user speech is detected:
    1. Immediately halts audio playback (sd.stop()).
    2. Cancels active TTS generation.
    3. Seamlessly captures and buffers the user's speech without losing words.
    """

    def __init__(
        self,
        interrupt_event: Optional[threading.Event] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
        vad: Optional[SileroVAD] = None,
    ) -> None:
        self.interrupt_event = interrupt_event or threading.Event()
        self.on_interrupt = on_interrupt
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.interrupted = False
        self.captured_audio: Optional[np.ndarray] = None
        self.enabled = getattr(config, "BARGE_IN_ENABLED", True)
        self.vad = vad or SileroVAD()

    def start(self) -> "BargeInMonitor":
        """Starts monitoring the microphone on a daemon thread."""
        if not self.enabled:
            return self

        self.interrupted = False
        self.captured_audio = None
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="JarvisBargeInMonitor")
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stops the monitoring thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
            self._thread = None

    def __enter__(self) -> "BargeInMonitor":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def _monitor_loop(self) -> None:
        # 512 samples = 32ms at 16kHz (native Silero VAD frame size)
        frame_samples = 512
        grace_period = getattr(config, "BARGE_IN_GRACE_PERIOD_SEC", 0.20)
        start_time = time.time()

        consecutive_speech = 0
        consecutive_needed = 2  # ~64ms debounce to filter transient speaker clicks

        # Rolling echo floor tracking
        echo_floor_history: deque[float] = deque(maxlen=20)
        # 500ms pre-roll buffer to retain initial phonemes
        pre_roll: deque[np.ndarray] = deque(maxlen=16)

        try:
            with open_input_stream(frame_samples) as stream:
                while not self._stop_event.is_set() and not self.interrupt_event.is_set():
                    chunk, _overflow = stream.read(frame_samples)
                    pcm = chunk[:, 0]
                    pre_roll.append(pcm)

                    # Calculate rolling baseline
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float64)**2)))
                    echo_floor_history.append(rms)
                    avg_echo = float(np.mean(echo_floor_history)) if echo_floor_history else 200.0

                    # Respect transient grace period at playback start
                    if time.time() - start_time < grace_period:
                        continue

                    # Evaluate speech with Silero VAD + echo suppression
                    is_voice, prob, frame_rms = self.vad.evaluate_frame(
                        pcm,
                        is_speaking=True,
                        echo_floor_rms=avg_echo,
                    )

                    if is_voice:
                        consecutive_speech += 1
                        if consecutive_speech >= consecutive_needed:
                            # Genuine user interruption confirmed!
                            print(f"\n  [barge-in] User voice detected (VAD={prob:.2f}, RMS={frame_rms:.0f}) -> cutting off TTS!")
                            self.interrupted = True
                            self.interrupt_event.set()

                            # 1. Kill speaker playback instantly
                            try:
                                sd.stop()
                            except Exception:
                                pass

                            if self.on_interrupt:
                                try:
                                    self.on_interrupt()
                                except Exception:
                                    pass

                            # 2. Seamlessly continue recording user's speech until silence
                            self.captured_audio = self._record_interruption_remainder(stream, pre_roll)
                            break
                    else:
                        consecutive_speech = 0
        except Exception as exc:
            logger.debug("BargeInMonitor audio stream notice: %s", exc)

    def _record_interruption_remainder(
        self,
        stream: sd.InputStream,
        pre_roll: deque[np.ndarray],
    ) -> Optional[np.ndarray]:
        """Continues recording the user's speech right after interruption until silence."""
        frame_samples = 512
        frames: list[np.ndarray] = list(pre_roll)

        silence_sec_needed = getattr(config, "VAD_SILENCE_DURATION_SEC", 1.2)
        silence_frames_needed = int(silence_sec_needed / (frame_samples / config.SAMPLE_RATE))
        max_frames = int(config.MAX_RECORD_SECONDS / (frame_samples / config.SAMPLE_RATE))

        silence_run = 0
        total_frames = 0

        while not self._stop_event.is_set() and total_frames < max_frames:
            try:
                chunk, _ = stream.read(frame_samples)
                pcm = chunk[:, 0]
                frames.append(pcm)
                total_frames += 1

                # Evaluate frame in listening mode
                is_voice, prob, _ = self.vad.evaluate_frame(pcm, is_speaking=False)
                if is_voice:
                    silence_run = 0
                else:
                    silence_run += 1
                    if silence_run >= silence_frames_needed:
                        break
            except Exception:
                break

        if not frames:
            return None

        audio = np.concatenate(frames).astype(np.float32) / 32768.0
        peak = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
        if peak > 0.01:
            audio = audio * (0.85 / peak)
        return audio
