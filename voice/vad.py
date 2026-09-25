"""Silero VAD (Voice Activity Detection) engine with acoustic echo suppression."""

from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

from voice import config

logger = logging.getLogger("jarvis.vad")


class SileroVAD:
    """High-accuracy, real-time Voice Activity Detection using Silero VAD (ONNX).
    Processes 512-sample (32ms) audio frames at 16kHz with <0.5ms inference latency.
    Includes acoustic echo shielding to prevent Jarvis from interrupting itself.
    """

    def __init__(self) -> None:
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            from faster_whisper.vad import get_vad_model
            self._model = get_vad_model()
            logger.info("Silero VAD engine initialized successfully via faster-whisper.")
        except Exception as exc:
            logger.warning("Could not initialize Silero VAD (%s); using energy-based fallback.", exc)
            self._model = None

    def get_speech_probability(self, frame: np.ndarray) -> float:
        """Evaluates speech probability in a 1D audio frame (512 samples at 16kHz)."""
        if len(frame) == 0:
            return 0.0

        # Ensure exactly 512 samples
        if len(frame) < 512:
            frame = np.pad(frame, (0, 512 - len(frame)))
        elif len(frame) > 512:
            frame = frame[:512]

        # Convert to float32 in [-1.0, 1.0]
        if frame.dtype == np.int16 or np.max(np.abs(frame)) > 1.5:
            float_frame = frame.astype(np.float32) / 32768.0
        else:
            float_frame = frame.astype(np.float32)

        if self._model is not None:
            try:
                out = self._model(float_frame, num_samples=512)
                return float(out[0])
            except Exception as exc:
                logger.debug("Silero VAD inference error: %s", exc)

        # Fallback energy heuristic if VAD model is unavailable
        rms = float(np.sqrt(np.mean(float_frame**2))) * 32768.0
        return min(1.0, max(0.0, rms / 800.0))

    def evaluate_frame(
        self,
        frame: np.ndarray,
        is_speaking: bool = False,
        echo_floor_rms: float = 0.0,
    ) -> Tuple[bool, float, float]:
        """Evaluates whether an audio frame contains genuine user speech.

        Returns:
            (is_speech: bool, speech_prob: float, frame_rms: float)
        """
        prob = self.get_speech_probability(frame)
        if frame.dtype == np.int16 or np.max(np.abs(frame)) > 1.5:
            rms = float(np.sqrt(np.mean(frame.astype(np.float64)**2)))
        else:
            rms = float(np.sqrt(np.mean(frame.astype(np.float64)**2))) * 32768.0

        if is_speaking:
            # During active TTS playback:
            # 1. Require high neural speech probability (default >= 0.75)
            thresh_prob = getattr(config, "VAD_BARGE_IN_THRESHOLD", 0.75)
            # 2. Require energy clearly exceeding speaker acoustic bleed floor
            min_rms = max(echo_floor_rms * 1.6, getattr(config, "VAD_BARGE_IN_MIN_RMS", 350.0))
            is_speech = (prob >= thresh_prob) and (rms >= min_rms)
        else:
            # Normal listening mode:
            thresh_prob = getattr(config, "VAD_LISTENING_THRESHOLD", 0.50)
            is_speech = prob >= thresh_prob

        return is_speech, prob, rms
