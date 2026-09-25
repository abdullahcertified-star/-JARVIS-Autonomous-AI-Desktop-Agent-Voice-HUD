"""High-Accuracy Voice Recognition Engine for AntiGravity IDE.

Solves mishearing issues, background static, and endless listening hangs through:
1. Automatic ambient noise calibration (`adjust_for_ambient_noise`).
2. High-accuracy Speech-to-Text via `faster-whisper` (`small.en`) with beam search and Silero VAD.
3. Strict `timeout` and `phrase_time_limit` so it never hangs on silence or static.
4. Dynamic audio normalization (-1 dBFS) for high-contrast speech feature extraction.
5. Vocabulary priming prompt to recognize technical terms, names, and scientific words accurately.
6. Real-time phonetic normalization to correct mishearings (e.g. CCADA -> cicada, APV4 -> IPv4).

Installation:
    pip install sounddevice numpy faster-whisper SpeechRecognition python-dotenv
"""

from __future__ import annotations

from collections import deque
import os
import re
import sys
import threading
import time
from typing import Callable, Optional

from faster_whisper import WhisperModel
import numpy as np
import sounddevice as sd
import speech_recognition as sr

# Audio standards required by Whisper and modern VAD engines
SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_DURATION_SEC = 0.03  # 30ms processing chunks
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_SEC)


def _rms(chunk: np.ndarray) -> float:
    """Computes Root Mean Square (RMS) energy of an int16 audio array."""
    if len(chunk) == 0:
        return 0.0
    return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))


_PHONETIC_FIXES = (
    (re.compile(r"\b[Jj]airuis\b", re.IGNORECASE), "Jarvis"),
    (re.compile(r"\b[Jj]airus\b", re.IGNORECASE), "Jarvis"),
    (re.compile(r"\b[Jj]arvus\b", re.IGNORECASE), "Jarvis"),
    (re.compile(r"\b[Jj]avis\b", re.IGNORECASE), "Jarvis"),
    (re.compile(r"\b[Jj]arves\b", re.IGNORECASE), "Jarvis"),
    (re.compile(r"\b[Jj]arviss\b", re.IGNORECASE), "Jarvis"),
    (re.compile(r"\b[Hh]ey\s+[Ss]ervice\b", re.IGNORECASE), "Hey Jarvis"),
    (re.compile(r"^\s*[Ss]ervice\b", re.IGNORECASE), "Jarvis"),
    (re.compile(r"\bAP[-\s]*V[-\s]*4\b", re.IGNORECASE), "IPv4"),
    (re.compile(r"\bAPV4\b", re.IGNORECASE), "IPv4"),
    (re.compile(r"\bAP[-\s]*V[-\s]*6\b", re.IGNORECASE), "IPv6"),
    (re.compile(r"\bAPV6\b", re.IGNORECASE), "IPv6"),
    (re.compile(r"\bC+ADA\b", re.IGNORECASE), "cicada"),
    (re.compile(r"\b[Cc][Cc][Aa][Dd][Aa]\b", re.IGNORECASE), "cicada"),
    (re.compile(r"\b[Ss]ecada\b", re.IGNORECASE), "cicada"),
    (re.compile(r"\b[Cc]ycada\b", re.IGNORECASE), "cicada"),
    (re.compile(r"\bFRAS\b", re.IGNORECASE), "France"),
    (re.compile(r"\bopen\s+(?:the\s+)?drive\s+app\b", re.IGNORECASE), "open drive F"),
    (re.compile(r"\b(?:the\s+)?drive\s+app\b", re.IGNORECASE), "drive F"),
    (re.compile(r"\b([CDEFGHcdefgh])\s+drive\b", re.IGNORECASE), r"drive \1"),
    (re.compile(r"\blocal\s+disk\s+([CDEFGHcdefgh])\b", re.IGNORECASE), r"drive \1"),
    (re.compile(r"\bdrive\s+see\b", re.IGNORECASE), "drive C"),
    (re.compile(r"\bdrive\s+dee\b", re.IGNORECASE), "drive D"),
    (re.compile(r"\bdrive\s+eff\b", re.IGNORECASE), "drive F"),
    (re.compile(r"\bdrive\s+gee\b", re.IGNORECASE), "drive G"),
)


def normalize_transcription(text: str) -> str:
    """Normalizes recognized speech, correcting common Whisper phonetic mishearings
    and collapsing spelled-out hyphenated words (e.g. 'FR-A-N-C-E' -> 'France')."""
    if not text:
        return ""
    result = text
    # 1. Collapse hyphenated spelled-out letters: 'F-R-A-N-C-E' or 'FR-A-N-C-E' -> 'FRANCE'
    result = re.sub(
        r"\b([A-Za-z]{1,2}(?:-[A-Za-z]{1,2})+)\b",
        lambda m: m.group(1).replace("-", ""),
        result,
    )
    # 2. Deduplicate uppercase repeats: 'FRAS, FRANCE' -> 'France'
    result = re.sub(
        r"\b([A-Z]{2,})\s*,\s*([A-Z]{3,})\b",
        lambda m: m.group(2).capitalize(),
        result,
    )
    for pattern, replacement in _PHONETIC_FIXES:
        result = pattern.sub(replacement, result)
    return result


class VoiceRecognitionEngine:
    """Optimized voice listener and transcriber for AntiGravity IDE and AI assistants."""

    DEFAULT_PROMPT = (
        "Hey Jarvis, Sir Abdullah. Open drive C, drive D, drive E, drive F, drive G, C:, D:, E:, F:, "
        "File Explorer, Local Disk C, Local Disk D, Local Disk E, Local Disk F, Windows folders, desktop, files, "
        "What is IPv4, IPv6, cicada, cicadas, insect, biology, science, "
        "AntiGravity IDE, code, Python, function, terminal, "
        "Windows desktop automation, IP address, Ethernet, Wi-Fi, volume, Chrome, YouTube, France, Paris."
    )

    def __init__(
        self,
        model_size: str = "small.en",
        device: str = "cpu",
        compute_type: str = "int8",
        input_device: Optional[int | str] = None,
        initial_prompt: Optional[str] = None,
    ) -> None:
        """Initializes the microphone stream and faster-whisper model."""
        self.device_index = self._resolve_device(input_device)
        self.ambient_noise_threshold = 50.0  # Default floor until calibrated
        self.initial_prompt = initial_prompt or self.DEFAULT_PROMPT

        print(f"[VoiceEngine] Loading high-accuracy Whisper model ({model_size}) on {device}...")
        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                cpu_threads=4,
                num_workers=1,
            )
        except Exception as exc:
            print(f"[VoiceEngine] Memory allocation warning ({exc}). Falling back to 'base.en'...")
            self.model = WhisperModel(
                "base.en",
                device=device,
                compute_type="int8",
                cpu_threads=2,
                num_workers=1,
            )
        print("[VoiceEngine] Whisper model loaded and ready.")

    def _resolve_device(self, selector: Optional[int | str]) -> Optional[int]:
        """Validates and resolves the microphone device index."""
        if selector is None or selector == "":
            return None
        if isinstance(selector, int) or (isinstance(selector, str) and selector.isdigit()):
            return int(selector)
        selector_str = str(selector).lower()
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0 and selector_str in dev.get("name", "").lower():
                return idx
        return None

    def adjust_for_ambient_noise(self, duration: float = 1.0) -> float:
        """Requirement 1: Automatic ambient noise calibration.
        Samples room acoustic static for `duration` seconds and sets a dynamic energy threshold.
        """
        print(f"[VoiceEngine] Calibrating for ambient background noise ({duration}s)...")
        chunk_samples = int(SAMPLE_RATE * 0.05)  # 50ms chunks
        num_chunks = max(int(duration / 0.05), 5)
        energy_samples: list[float] = []

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=chunk_samples,
                device=self.device_index,
            ) as stream:
                for _ in range(num_chunks):
                    data, _ = stream.read(chunk_samples)
                    energy_samples.append(_rms(data[:, 0]))
        except Exception as exc:
            print(f"[VoiceEngine] Warning during calibration: {exc}. Using fallback threshold.")
            self.ambient_noise_threshold = 60.0
            return self.ambient_noise_threshold

        avg_energy = float(np.mean(energy_samples)) if energy_samples else 20.0
        # Dynamic ratio: 2.0x ambient floor with safe bounding (filters background fan/static, protects quiet speech)
        self.ambient_noise_threshold = max(min(avg_energy * 2.0, 500.0), 25.0)
        print(
            f"[VoiceEngine] Calibrated: Noise floor={avg_energy:.1f} RMS | "
            f"Active Speech Threshold={self.ambient_noise_threshold:.1f} RMS"
        )
        return self.ambient_noise_threshold

    def listen(
        self,
        timeout: float = 5.0,
        phrase_time_limit: float = 10.0,
        silence_duration: float = 0.6,
        on_level: Optional[Callable[[float], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[np.ndarray]:
        """Requirement 3: Strict phrase time limit and timeout recording.
        - timeout: Max seconds to wait for speech to begin.
        - phrase_time_limit: Hard maximum duration for the speech utterance.
        - silence_duration: Seconds of trailing silence before auto-stopping.
        """
        max_chunks = int(phrase_time_limit / FRAME_DURATION_SEC)
        start_timeout_chunks = int(timeout / FRAME_DURATION_SEC)
        silence_needed = int(silence_duration / FRAME_DURATION_SEC)

        frames: list[np.ndarray] = []
        pre_roll: deque[np.ndarray] = deque(maxlen=15)  # ~450ms pre-roll to protect initial vowels and consonants
        speech_started = False
        silence_count = 0

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
                device=self.device_index,
            ) as stream:
                for i in range(max_chunks):
                    if stop_event is not None and stop_event.is_set():
                        break

                    chunk, _overflow = stream.read(FRAME_SAMPLES)
                    pcm = chunk[:, 0]
                    energy = _rms(pcm)
                    is_speech = energy > self.ambient_noise_threshold

                    if on_level:
                        on_level(min(energy / 3500.0, 1.0))

                    if not speech_started:
                        if is_speech:
                            speech_started = True
                            frames.extend(pre_roll)
                            frames.append(pcm)
                        else:
                            pre_roll.append(pcm)
                            if i >= start_timeout_chunks:
                                # Timeout expired with no speech detected
                                return None
                        continue

                    # Speech is in progress
                    frames.append(pcm)
                    if is_speech:
                        silence_count = 0
                    else:
                        silence_count += 1

                    if silence_count >= silence_needed:
                        # Trailing silence detected -- finish recording
                        break
        except Exception as exc:
            print(f"[VoiceEngine] Audio stream error: {exc}")
            if not frames:
                return None

        if not frames:
            return None

        # Convert int16 -> normalized float32 in [-1.0, 1.0]
        audio = np.concatenate(frames).astype(np.float32) / 32768.0

        # Peak normalization (-1 dBFS peak / ~0.85): ensures Whisper feature extractor
        # receives pristine, high-contrast spectrograms even with low mic gain
        peak = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
        if peak > 0.01:
            audio = audio * (0.85 / peak)

        return audio

    def transcribe(self, audio: np.ndarray) -> str:
        """Requirement 2: High-accuracy Speech-to-Text inference via faster-whisper."""
        if audio is None or len(audio) == 0:
            return ""

        segments, _info = self.model.transcribe(
            audio,
            language="en",
            initial_prompt=self.initial_prompt,
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300, speech_pad_ms=200),
        )

        text = " ".join(segment.text.strip() for segment in segments).strip()
        return normalize_transcription(text)

    def listen_and_transcribe(
        self,
        timeout: float = 5.0,
        phrase_time_limit: float = 10.0,
    ) -> str:
        """High-level one-shot capture and transcription."""
        audio = self.listen(timeout=timeout, phrase_time_limit=phrase_time_limit)
        if audio is None:
            return ""
        return self.transcribe(audio)


# --- Standalone Interactive Demo for AntiGravity IDE ---
def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    print("=" * 65)
    print("  AntiGravity IDE - Voice Recognition Engine (High Accuracy)  ")
    print("=" * 65)

    # 1. Initialize engine (uses locally cached 'small.en' or 'base.en')
    model_name = os.getenv("JARVIS_WHISPER_MODEL", "small.en")
    engine = VoiceRecognitionEngine(model_size=model_name)

    # 2. Run automatic ambient noise calibration
    engine.adjust_for_ambient_noise(duration=1.0)

    print("\nListening for speech (Press Ctrl+C to quit)...")
    try:
        while True:
            print("\n[Listening] Speak your command now...")
            text = engine.listen_and_transcribe(timeout=5.0, phrase_time_limit=10.0)

            if not text:
                print("  (No speech detected or timed out -- listening again)")
                continue

            print(f"  >>> Recognized: \"{text}\"")
    except KeyboardInterrupt:
        print("\n[VoiceEngine] Stopped.")


if __name__ == "__main__":
    main()
