"""Cinematic Sound Effects (SFX) engine for the JARVIS desktop voice experience.

Provides Marvel/Iron Man style audio feedback:
- wake: futuristic upward chime upon wake word detection.
- listening_end: subtle digital acknowledgment when speech recording finishes.
- positive: crisp affirmative dual-tone on action success.
- negative: low soft warning tone on failure.
- standby: descending harmonic sleep chime when entering standby.
- shutdown: resonant power-down chime when terminating.

All audio files are cached in memory as pre-scaled float32 arrays for instant,
zero-latency playback on non-blocking background threads.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import sounddevice as sd
import soundfile as sf

from voice import config

_SOUNDS_DIR = Path(__file__).parent / "sounds"


class SoundEffects:
    """Manages zero-latency playback of cinematic UI sound effects."""

    def __init__(self) -> None:
        self.enabled = getattr(config, "SFX_ENABLED", True)
        self.volume = max(0.0, min(1.0, getattr(config, "SFX_VOLUME", 0.45)))
        self._cache: dict[str, tuple[any, int]] = {}
        self._load_sounds()

    def _load_sounds(self) -> None:
        """Pre-loads all sound files into RAM to avoid runtime disk I/O."""
        if not _SOUNDS_DIR.exists():
            return

        for wav_path in _SOUNDS_DIR.glob("*.wav"):
            try:
                data, sr = sf.read(str(wav_path), dtype="float32")
                self._cache[wav_path.stem] = (data * self.volume, sr)
            except Exception as exc:
                print(f"(Failed to load SFX {wav_path.name}: {exc})")

    def play(self, sound_name: str) -> None:
        """Plays a sound asynchronously on a daemon thread without blocking the caller."""
        if not self.enabled:
            return

        item = self._cache.get(sound_name)
        if not item:
            return

        audio, sr = item

        def _play_worker() -> None:
            try:
                # Use sounddevice to play the pre-cached in-memory array
                sd.play(audio, samplerate=sr)
            except Exception:
                pass

        threading.Thread(target=_play_worker, daemon=True).start()

    def play_wake(self) -> None:
        self.play("wake")

    def play_listening_end(self) -> None:
        self.play("listening_end")

    def play_positive(self) -> None:
        self.play("positive")

    def play_negative(self) -> None:
        self.play("negative")

    def play_standby(self) -> None:
        self.play("standby")

    def play_shutdown(self) -> None:
        self.play("shutdown")


_sfx_instance: Optional[SoundEffects] = None
_sfx_lock = threading.Lock()


def get_sfx() -> SoundEffects:
    """Returns the singleton SoundEffects manager."""
    global _sfx_instance
    if _sfx_instance is None:
        with _sfx_lock:
            if _sfx_instance is None:
                _sfx_instance = SoundEffects()
    return _sfx_instance
