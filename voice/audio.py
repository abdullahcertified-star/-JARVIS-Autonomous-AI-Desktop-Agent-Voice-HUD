"""Microphone I/O: wake-word detection and record-until-silence capture.

Both operate on 16kHz mono int16 audio, which is what openWakeWord requires
and what Whisper expects -- no resampling needed between the two stages.
"""

from __future__ import annotations

from collections import deque
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

# Configure ONNX Runtime to disable BFCArena memory pre-allocation.
# This prevents BFCArena::AllocateRawInternal Out-Of-Memory crashes on Windows.
try:
    import onnxruntime as _ort

    _orig_SessionOptions = _ort.SessionOptions

    def _patched_SessionOptions(*args, **kwargs):
        opts = _orig_SessionOptions(*args, **kwargs)
        opts.enable_cpu_mem_arena = False
        return opts

    _ort.SessionOptions = _patched_SessionOptions

    _orig_InferenceSession = _ort.InferenceSession

    def _patched_InferenceSession(path_or_bytes, *args, **kwargs):
        sess_options = kwargs.get("sess_options")
        if sess_options is None:
            sess_options = _orig_SessionOptions()
            kwargs["sess_options"] = sess_options
        sess_options.enable_cpu_mem_arena = False
        return _orig_InferenceSession(path_or_bytes, *args, **kwargs)

    _ort.InferenceSession = _patched_InferenceSession
except Exception:
    pass

from openwakeword.model import Model
from openwakeword.utils import download_models

from voice import config

_FRAME_SAMPLES = 1280  # openWakeWord wants multiples of 80ms at 16kHz


class StopRequested(Exception):
    """Raised out of a listen/record loop when its stop_event gets set --
    e.g. the orb window was closed. Background threads never see Ctrl+C
    (only the main thread does), so this is the actual shutdown mechanism."""

# Raw int16 RMS above this is treated as "as loud as it gets" for UI level
# meters (0..1) -- comfortably above normal speech volume, below clipping.
_LEVEL_METER_CEILING = 4000.0


_resolved_device_cache: object = "__unset__"  # sentinel; a resolved value can legitimately be None


def _rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))


def _device_actually_captures_audio(index: int) -> bool:
    """The same physical mic is typically exposed multiple times under
    different Windows audio host APIs (MME/DirectSound/WASAPI/WDM-KS), and
    on real hardware these are NOT interchangeable: WDM-KS tends to reject
    the blocking read API outright, some WASAPI endpoints reject the
    required sample rate, and some "phantom" duplicate entries open and
    read successfully but deliver exact all-zero silence forever -- not
    quiet, literally 0.0, which even a silent room's electrical noise floor
    doesn't produce. So: actually open, read several real frames (with a
    hard timeout in case a candidate just hangs), and require at least one
    frame with genuinely non-zero signal before trusting this device."""
    result: dict[str, bool] = {"ok": False}

    def _try() -> None:
        try:
            with sd.InputStream(
                samplerate=config.SAMPLE_RATE, channels=1, dtype="int16", blocksize=_FRAME_SAMPLES, device=index
            ) as stream:
                for _ in range(5):
                    frame, _overflow = stream.read(_FRAME_SAMPLES)
                    if _rms(frame[:, 0]) > 0:
                        result["ok"] = True
                        return
        except Exception:
            pass

    probe_thread = threading.Thread(target=_try, daemon=True)
    probe_thread.start()
    probe_thread.join(timeout=3.0)
    return result["ok"] and not probe_thread.is_alive()


def resolve_input_device() -> int | None:
    """Resolves JARVIS_INPUT_DEVICE (index or name substring) to a device
    index, verifying it actually works before returning it. Returns None
    (let PortAudio pick) only if unset -- but unset is not recommended,
    since Windows' "default" device is not always the mic you actually want
    (e.g. an empty physical jack instead of a laptop's built-in array).

    Device indices are not stable across process runs on Windows, so the
    result is re-resolved fresh each run but cached for this run's lifetime
    (probing opens/closes a real stream, which has a small cost)."""
    global _resolved_device_cache
    if _resolved_device_cache != "__unset__":
        return _resolved_device_cache  # type: ignore[return-value]

    selector = config.INPUT_DEVICE.strip()
    if not selector:
        _resolved_device_cache = None
        return None

    if selector.isdigit():
        _resolved_device_cache = int(selector)
        return _resolved_device_cache  # type: ignore[return-value]

    candidates = [
        index
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0 and selector.lower() in device["name"].lower()
    ]
    if not candidates:
        raise RuntimeError(
            f"No input device matched JARVIS_INPUT_DEVICE={selector!r}. "
            "Run `python -m voice.list_devices` to see available devices."
        )

    # The same physical mic is usually exposed multiple times under
    # different Windows audio host APIs (MME/DirectSound/WASAPI/WDM-KS).
    # Which one actually works is NOT predictable from the API name --
    # on this codebase's dev machine, WASAPI failed to open, DirectSound
    # opened but silently returned all-zero audio forever, and legacy MME
    # was the only one that worked. So: don't guess a preference order,
    # just test every candidate for real and use the first one that
    # actually captures genuine (non-zero) audio.
    host_apis = sd.query_hostapis()
    for index in candidates:
        if _device_actually_captures_audio(index):
            _resolved_device_cache = index
            device = sd.query_devices(index)
            api_name = host_apis[device["hostapi"]]["name"]
            print(f"Using microphone: {device['name']} (index {index}, {api_name})")
            return index

    raise RuntimeError(
        f"Found {len(candidates)} input device(s) matching JARVIS_INPUT_DEVICE={selector!r}, "
        "but none of them actually captured real audio (tried opening and reading from each). "
        "Try a different (less specific) substring in .env, or check Windows microphone "
        "privacy settings -- run `python -m voice.list_devices` to see all options."
    )


def _open_input_stream(blocksize: int) -> sd.InputStream:
    """Opens an InputStream, retrying a few times on failure. Legacy Windows
    audio host APIs (MME in particular -- which on some systems is the only
    one that actually captures real audio, see resolve_input_device) can
    intermittently throw a spurious 'device ID out of range' error on the
    very next open right after a previous stream on the same device was
    just closed. A short retry absorbs that instead of crashing the loop."""
    last_exc: Exception | None = None
    for _attempt in range(4):
        try:
            return sd.InputStream(
                samplerate=config.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=blocksize,
                device=resolve_input_device(),
            )
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised as-is
            last_exc = exc
            time.sleep(0.3)
    raise last_exc  # type: ignore[misc]


class WakeWordListener:
    """Blocks until the configured wake word is heard, then returns."""

    def __init__(
        self,
        stop_event: threading.Event | None = None,
        pause_event: threading.Event | None = None,
    ) -> None:
        download_models([config.WAKE_WORD_MODEL])  # no-op if already cached
        try:
            self._model = Model(wakeword_models=[config.WAKE_WORD_MODEL], inference_framework="onnx")
        except Exception as exc:
            print(f"Warning: ONNX wake word model initial attempt encountered: {exc}. Retrying...")
            time.sleep(0.5)
            self._model = Model(wakeword_models=[config.WAKE_WORD_MODEL], inference_framework="onnx")
        self._stop_event = stop_event
        self._pause_event = pause_event

    def close(self) -> None:
        pass  # nothing to release -- openWakeWord has no persistent handle

    def listen(self) -> None:
        """Blocks until the wake word is detected. Raises StopRequested if
        stop_event gets set while waiting (checked every ~80ms). While
        pause_event is set, the mic stream stays open but frames are just
        discarded -- no detection happens until it's cleared (mute button).

        Legacy Windows audio host APIs (MME in particular) can throw
        PortAudioError not just on open but mid-stream, in various error
        "flavors" ('device ID out of range', 'no driver installed', ...).
        Rather than special-case each one, any audio error here just
        reopens a fresh stream and keeps listening -- this loop runs
        forever anyway, so a dropped stream is not fatal."""
        # Reset internal feature and prediction buffer so previous speech cannot trigger a false wake word
        if hasattr(self._model, "reset"):
            self._model.reset()

        while True:
            try:
                with _open_input_stream(_FRAME_SAMPLES) as stream:
                    while True:
                        if self._stop_event is not None and self._stop_event.is_set():
                            raise StopRequested
                        frame, _overflow = stream.read(_FRAME_SAMPLES)
                        if self._pause_event is not None and self._pause_event.is_set():
                            continue
                        pcm = frame[:, 0]
                        rms = _rms(pcm)
                        score = self._model.predict(pcm).get(config.WAKE_WORD_MODEL, 0.0)
                        # Only print when there's an actual attempt (mic picked up
                        # real sound and the model reacted at all) -- otherwise this
                        # would be a wall of near-zero noise every 80ms.
                        thresh = _ambient_noise_threshold or config.SILENCE_RMS_THRESHOLD
                        if score > 0.05 or rms > thresh:
                            print(f"  [wake word] level={rms:.0f} score={score:.3f} (threshold={config.WAKE_WORD_THRESHOLD})")
                        if score >= config.WAKE_WORD_THRESHOLD:
                            if hasattr(self._model, "reset"):
                                self._model.reset()
                            return
            except StopRequested:
                raise
            except sd.PortAudioError as exc:
                print(f"  [wake word] audio glitch, reopening mic: {exc}")
                time.sleep(0.3)
            except Exception as exc:
                print(f"  [wake word] audio/inference glitch, resuming: {exc}")
                time.sleep(0.3)


_ambient_noise_threshold: float | None = None


def adjust_for_ambient_noise(duration: float = 1.0) -> float:
    """Calibrates microphone input to ambient background noise level.
    Samples room static/noise for `duration` seconds and sets an adaptive RMS threshold."""
    global _ambient_noise_threshold
    chunk_samples = int(config.SAMPLE_RATE * 0.05)  # 50ms chunks
    chunks_count = max(int(duration / 0.05), 5)
    noise_rms_values = []
    try:
        with _open_input_stream(chunk_samples) as stream:
            for _ in range(chunks_count):
                chunk, _ = stream.read(chunk_samples)
                noise_rms_values.append(_rms(chunk[:, 0]))
    except Exception as exc:
        print(f"  [calibration] error during ambient noise check: {exc}")
        _ambient_noise_threshold = config.SILENCE_RMS_THRESHOLD
        return _ambient_noise_threshold

    avg_noise = float(np.mean(noise_rms_values)) if noise_rms_values else 200.0
    # Dynamic threshold: 2.0x ambient noise floor, bounded between 25.0 and 500.0 RMS
    calibrated = max(min(avg_noise * 2.0, 500.0), 25.0)
    _ambient_noise_threshold = calibrated
    print(f"  [ambient noise calibrated] noise_floor={avg_noise:.1f} RMS -> dynamic_threshold={calibrated:.1f} RMS")
    return calibrated


def get_ambient_threshold() -> float:
    """Returns the calibrated ambient noise threshold, falling back to default config if uncalibrated."""
    global _ambient_noise_threshold
    return _ambient_noise_threshold or config.SILENCE_RMS_THRESHOLD


# Public aliases for barge-in audio capture
open_input_stream = _open_input_stream
calc_rms = _rms



def record_until_silence(
    on_level: Callable[[float], None] | None = None,
    stop_event: threading.Event | None = None,
    phrase_time_limit: float | None = None,
    timeout: float | None = None,
) -> np.ndarray | None:
    """Records from the mic starting right after the wake word.

    Uses automatic ambient noise threshold to filter room static.
    Waits up to `timeout` seconds for speech to start; if none comes, returns None.
    Records up to `phrase_time_limit` seconds (or until speech stops), then normalizes
    and returns the audio as a 1D float32 array in [-1, 1].
    """
    global _ambient_noise_threshold
    if _ambient_noise_threshold is None:
        adjust_for_ambient_noise(duration=0.8)

    active_threshold = _ambient_noise_threshold or config.SILENCE_RMS_THRESHOLD
    max_duration = phrase_time_limit or config.MAX_RECORD_SECONDS
    start_timeout = timeout or config.SPEECH_START_TIMEOUT_SEC

    chunk_samples = int(config.SAMPLE_RATE * 0.03)  # 30ms chunks
    start_timeout_chunks = int(start_timeout / 0.03)
    max_speech_chunks = int(max_duration / 0.03)
    silence_chunks_needed = int(config.SILENCE_DURATION_SEC / 0.03)

    frames: list[np.ndarray] = []
    pre_roll: deque[np.ndarray] = deque(maxlen=15)  # ~450ms pre-roll buffer to preserve soft initial phonemes and vowels
    speech_started = False
    silence_run = 0
    wait_chunks = 0
    speech_chunks = 0

    try:
        with _open_input_stream(chunk_samples) as stream:
            while True:
                if stop_event is not None and stop_event.is_set():
                    raise StopRequested
                chunk, _overflow = stream.read(chunk_samples)
                pcm = chunk[:, 0]
                rms = _rms(pcm)
                loud = rms > active_threshold

                if on_level is not None:
                    on_level(min(rms / _LEVEL_METER_CEILING, 1.0))

                if not speech_started:
                    if loud:
                        speech_started = True
                        frames.extend(pre_roll)
                        frames.append(pcm)
                    else:
                        pre_roll.append(pcm)
                        wait_chunks += 1
                        if wait_chunks >= start_timeout_chunks:
                            return None  # nobody spoke within the start timeout window
                    continue

                frames.append(pcm)
                speech_chunks += 1
                silence_run = 0 if loud else silence_run + 1
                if silence_run >= silence_chunks_needed or speech_chunks >= max_speech_chunks:
                    break
    except sd.PortAudioError as exc:
        print(f"  [recording] audio glitch: {exc}")
        if not frames:
            return None

    if not frames:
        return None

    # Trim excess trailing silence frames while preserving natural ~300ms room decay
    excess_silence = max(0, silence_run - 10)
    if excess_silence > 0 and len(frames) > excess_silence:
        frames = frames[:-excess_silence]

    audio = np.concatenate(frames).astype(np.float32) / 32768.0

    # Audio peak normalization: boosts quiet utterances to clean -1 dBFS peak (~0.85)
    # so Whisper receives crisp, high-contrast Mel spectrograms
    peak = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
    if peak > 0.01:
        audio = audio * (0.85 / peak)

    return audio
