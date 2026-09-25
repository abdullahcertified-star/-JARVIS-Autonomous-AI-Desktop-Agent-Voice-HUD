"""Configuration for the voice client (wake word -> record -> transcribe ->
send to the JARVIS Gemini agent -> speak the reply).

This program connects directly to the in-process JARVIS AI agent (agent.py)
powered by the Google GenAI SDK.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# openWakeWord is fully free and offline -- no account/key needed. "hey_jarvis"
# is one of its official pretrained models, downloaded automatically on first run.
WAKE_WORD_MODEL: str = os.getenv("JARVIS_WAKE_WORD_MODEL", "hey_jarvis")
WAKE_WORD_THRESHOLD: float = float(os.getenv("JARVIS_WAKE_WORD_THRESHOLD", "0.5"))

# Speech-to-Text (STT) engine: 'auto', 'speech_recognition' (Google STT, zero-memory, ultra-fast), or 'whisper'
STT_ENGINE: str = os.getenv("JARVIS_STT_ENGINE", "auto")

# faster-whisper model size: tiny.en/base.en/small.en trade speed for
# accuracy, in that order. base.en is a good default for short commands.
WHISPER_MODEL_SIZE: str = os.getenv("JARVIS_WHISPER_MODEL", "base.en")
WHISPER_DEVICE: str = os.getenv("JARVIS_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE: str = os.getenv("JARVIS_WHISPER_COMPUTE_TYPE", "int8")
WHISPER_CPU_THREADS: int = int(os.getenv("JARVIS_WHISPER_CPU_THREADS", "2"))

# Gemini TTS -- uses Google AI Studio's neural TTS (google-genai).
# API key: same key you use for the n8n Gemini agent -- get one at
# https://aistudio.google.com/apikey and put it in .env as GEMINI_API_KEY.
# Model: gemini-2.5-flash-preview-tts (fast, low latency) or
#         gemini-2.5-pro-preview-tts (highest quality, slower).
# Voice: Fenrir, Charon, Kore, Puck, Aoede, etc.
#        Full list: https://ai.google.dev/gemini-api/docs/speech-generation
# Speech Synthesis (TTS)
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_TTS_MODEL: str = os.getenv("GEMINI_TTS_MODEL", "edge-tts")
GEMINI_TTS_VOICE: str = os.getenv("GEMINI_TTS_VOICE", "Algenib")

# Edge Neural TTS settings (deep cinematic movie/anime human voice)
EDGE_VOICE: str = os.getenv("JARVIS_EDGE_VOICE", "en-US-ChristopherNeural")
EDGE_PITCH: str = os.getenv("JARVIS_EDGE_PITCH", "-4Hz")
EDGE_RATE: str = os.getenv("JARVIS_EDGE_RATE", "-2%")
COMMA_PAUSE_SEC: float = float(os.getenv("JARVIS_COMMA_PAUSE_SEC", "0.7"))
PERIOD_PAUSE_SEC: float = float(os.getenv("JARVIS_PERIOD_PAUSE_SEC", "1.0"))
AI_SPEECH_CORRECTION: bool = os.getenv("JARVIS_AI_SPEECH_CORRECTION", "true").lower() in ("true", "1", "yes")

SAMPLE_RATE = 16_000  # required by both openWakeWord and Whisper

# Which microphone to use. Windows' "default" input device is not always
# the one you'd expect (e.g. an empty physical mic jack instead of the
# laptop's built-in array) -- set this explicitly rather than trust it.
# Accepts a device index (e.g. "13") or a substring of the device name
# (e.g. "Microphone Array"). Run `python -m voice.list_devices` to see options.
INPUT_DEVICE: str = os.getenv("JARVIS_INPUT_DEVICE", "")

# Recording tuning: snappy silence cutoff, strict timeout limits, and ambient noise calibration.
SPEECH_START_TIMEOUT_SEC: float = float(os.getenv("JARVIS_SPEECH_START_TIMEOUT", "4.0"))
SILENCE_DURATION_SEC: float = float(os.getenv("JARVIS_SILENCE_DURATION", "2.5"))
MAX_RECORD_SECONDS: float = float(os.getenv("JARVIS_MAX_RECORD_SECONDS", "30.0"))
SILENCE_RMS_THRESHOLD: float = float(os.getenv("JARVIS_SILENCE_RMS", "250.0"))
AMBIENT_CALIBRATE_SEC: float = float(os.getenv("JARVIS_AMBIENT_CALIBRATE_SEC", "1.0"))

# Continuous conversation mode: how long Jarvis stays awake waiting for follow-up commands before returning to sleep (45 seconds)
CONVERSATION_TIMEOUT_SEC: float = float(os.getenv("JARVIS_CONVERSATION_TIMEOUT", "45.0"))

# Cinematic Sound Effects (Marvel HUD audio cues)
SFX_ENABLED: bool = os.getenv("JARVIS_SFX_ENABLED", "true").lower() in ("true", "1", "yes")
SFX_VOLUME: float = float(os.getenv("JARVIS_SFX_VOLUME", "0.45"))

# Voice Interruption & Barge-in (instant speech cutoff when user speaks)
BARGE_IN_ENABLED: bool = os.getenv("JARVIS_BARGE_IN_ENABLED", "true").lower() in ("true", "1", "yes")
BARGE_IN_ENERGY_RATIO: float = float(os.getenv("JARVIS_BARGE_IN_ENERGY_RATIO", "3.0"))
BARGE_IN_GRACE_PERIOD_SEC: float = float(os.getenv("JARVIS_BARGE_IN_GRACE_PERIOD", "0.25"))

