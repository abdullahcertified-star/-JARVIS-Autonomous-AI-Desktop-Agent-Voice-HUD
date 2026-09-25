"""Diagnostic tool: prints live mic level + "hey jarvis" confidence score.

Run this instead of main.py when the wake word isn't triggering, to see
exactly what the microphone and wake-word model are actually seeing.

    .venv\\Scripts\\python -m voice.diagnose
"""

from __future__ import annotations

import numpy as np
import sounddevice as sd
from openwakeword.model import Model
from openwakeword.utils import download_models

from voice import config
from voice.audio import _open_input_stream, resolve_input_device

_FRAME_SAMPLES = 1280


def _rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))


def main() -> None:
    device = resolve_input_device()
    if device is None:
        device_name = sd.query_devices(kind="input")["name"] + " (Windows default -- consider setting JARVIS_INPUT_DEVICE)"
    else:
        device_name = sd.query_devices(device)["name"]
    print("Using input device:", device_name)
    print(f"Sample rate: {config.SAMPLE_RATE} Hz")
    print()

    download_models([config.WAKE_WORD_MODEL])
    model = Model(wakeword_models=[config.WAKE_WORD_MODEL], inference_framework="onnx")

    print(f"Threshold for a detection: {config.WAKE_WORD_THRESHOLD}")
    print("Speak normally, then try \"Hey Jarvis\". Watch the score column. Ctrl+C to stop.\n")
    print(f"{'mic level':>10}  {'hey_jarvis score':>17}")

    # Same resilience as voice/audio.py: legacy Windows audio APIs (MME in
    # particular) can throw PortAudioError mid-stream in various flavors --
    # reopen and keep going instead of crashing the whole diagnostic run.
    while True:
        try:
            with _open_input_stream(_FRAME_SAMPLES) as stream:
                while True:
                    frame, _overflow = stream.read(_FRAME_SAMPLES)
                    pcm = frame[:, 0]
                    level = _rms(pcm)
                    scores = model.predict(pcm)
                    score = scores.get(config.WAKE_WORD_MODEL, 0.0)

                    bar = "#" * min(int(level / 200), 40)
                    marker = "  <-- DETECTED" if score >= config.WAKE_WORD_THRESHOLD else ""
                    print(f"{level:10.0f}  {score:17.3f}  {bar}{marker}")
        except sd.PortAudioError as exc:
            print(f"(audio glitch, reopening mic: {exc})")
        except KeyboardInterrupt:
            print("\nStopped.")
            return


if __name__ == "__main__":
    main()
