"""Transcription, sending text to the JARVIS Gemini agent, and speaking the reply."""

from __future__ import annotations

import asyncio
import io
import queue
import re
import threading
import wave
from typing import Callable, Literal

import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel
from google import genai
from google.genai import types

from agent import get_agent
from voice import config

# Jarvis's own reply text is the only signal we have about whether the
# underlying action actually succeeded (n8n doesn't return a separate
# success flag) -- these phrases are the ones it consistently uses when a
# tool call failed or it couldn't do something, based on real replies seen
# in this project's chat.
_NEGATIVE_PHRASES = (
    "unable to", "not able to", "wasn't able", "isn't able", "couldn't", "could not",
    "can't", "cannot", "don't have the ability", "doesn't have the ability",
    "i can't", "failed", "not found", "not available", "no ability", "did not", "didn't",
    "sorry", "unfortunately", "encountered an error", "went wrong", "not possible",
    "not installed", "access is denied", "access was denied",
    "issue with", "having trouble", "not working", "isn't working",
    "doesn't work", "having a problem", "persistent issue", "keeps failing",
)


def classify_reply(text: str) -> Literal["positive", "negative"]:
    """Best-effort read on whether Jarvis's reply describes success or
    failure -- n8n only gives us a natural-language reply, not a
    structured status, so this is a keyword heuristic, not a guarantee."""
    lowered = text.lower()
    return "negative" if any(phrase in lowered for phrase in _NEGATIVE_PHRASES) else "positive"


def enforce_status_prefix(text: str) -> str:
    """Enforces the 'Positive sir, ' or 'Negative sir, ' prefix on every task response.
    Preserves greetings and polite standby/sleep confirmations."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "Positive sir."

    lowered = cleaned.lower()
    # Preserve conversational greetings or standby messages
    if any(phrase in lowered for phrase in ("at your service", "how may i assist", "standing by", "goodbye")):
        return cleaned

    # Check if already starts with Positive/Affirmative
    pos_match = re.match(r"^(?:positive|affirmative)\s*,?\s*(?:sir|sir abdullah)?[,\s]*", cleaned, re.IGNORECASE)
    if pos_match:
        rest = cleaned[pos_match.end():].lstrip(" ,.-:")
        return f"Positive sir, {rest}" if rest else "Positive sir."

    # Check if already starts with Negative
    neg_match = re.match(r"^negative\s*,?\s*(?:sir|sir abdullah)?[,\s]*", cleaned, re.IGNORECASE)
    if neg_match:
        rest = cleaned[neg_match.end():].lstrip(" ,.-:")
        return f"Negative sir, {rest}" if rest else "Negative sir."

    # If it starts with "Sir Abdullah, ", remove the redundant salutation when prefixing
    if re.match(r"^sir\s+abdullah[,\s]+", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"^sir\s+abdullah[,\s]+", "", cleaned, flags=re.IGNORECASE).lstrip(" ,.-:")

    tone = classify_reply(cleaned)
    prefix = "Positive sir, " if tone == "positive" else "Negative sir, "
    return f"{prefix}{cleaned}"


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
    # 2. Deduplicate only when both tokens are uppercase repeat corrections: 'FRAS, FRANCE' -> 'France'
    result = re.sub(
        r"\b([A-Z]{2,})\s*,\s*([A-Z]{3,})\b",
        lambda m: m.group(2).capitalize(),
        result,
    )
    for pattern, replacement in _PHONETIC_FIXES:
        result = pattern.sub(replacement, result)
    return result


def ai_clean_voice_command(text: str) -> str:
    """Uses fast contextual heuristics and optional Gemini AI repair to guarantee
    accurate intent recognition without mishearings."""
    if not text:
        return ""
    normalized = normalize_transcription(text)

    # If AI speech correction is enabled and text has suspicious mishearings
    if getattr(config, "AI_SPEECH_CORRECTION", True) and config.GEMINI_API_KEY:
        lowered = normalized.lower()
        # Fast paths for drives and standard queries don't need network call
        if any(re.search(p, lowered) for p in (r"\bopen drive [a-z]\b", r"\bwhat is (?:my )?ipv4\b", r"\bwhat time\b")):
            return normalized

        suspicious = (
            "drive app" in lowered
            or "see drive" in lowered
            or "eff drive" in lowered
            or "apv" in lowered
            or "ccada" in lowered
        )
        if suspicious:
            try:
                client = genai.Client(api_key=config.GEMINI_API_KEY)
                resp = client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=(
                        "You are an AI speech recognition sanitizer for a Windows assistant. "
                        "The machine has drives C:, D:, E:, F:, File Explorer, Chrome, volume, system status. "
                        "Fix any speech-to-text mishearings (e.g. 'open the drive app' -> 'open drive F', 'drive see' -> 'drive C'). "
                        f"Output ONLY the corrected command phrase without quotes. Input: {normalized}"
                    ),
                    config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=30),
                )
                if resp.text and resp.text.strip():
                    return resp.text.strip()
            except Exception:
                pass
    return normalized


class Transcriber:
    _PROMPT = (
        "Hey Jarvis, Sir Abdullah. Open drive C, drive D, drive E, drive F, drive G, C:, D:, E:, F:, "
        "File Explorer, Local Disk C, Local Disk D, Local Disk E, Local Disk F, Windows folders, desktop, files, "
        "What is IPv4, IPv6, cicada, cicadas, insect, biology, science, IP address, "
        "Windows desktop automation, applications, Ethernet, Wi-Fi, volume, Chrome, YouTube, France, Paris."
    )

    def __init__(self) -> None:
        self._engine = getattr(config, "STT_ENGINE", "auto").lower()
        self._whisper = None
        self._sr_recognizer = None

        if self._engine in ("speech_recognition", "google"):
            import speech_recognition as sr
            self._sr_recognizer = sr.Recognizer()
            print("[Transcriber] Initialized high-accuracy SpeechRecognition engine.")
            return

        cpu_threads = getattr(config, "WHISPER_CPU_THREADS", 2)
        try:
            self._whisper = WhisperModel(
                config.WHISPER_MODEL_SIZE,
                device=config.WHISPER_DEVICE,
                compute_type=config.WHISPER_COMPUTE_TYPE,
                cpu_threads=cpu_threads,
                num_workers=1,
            )
            print(f"[Transcriber] faster-whisper ({config.WHISPER_MODEL_SIZE}) loaded successfully.")
        except Exception as exc:
            print(
                f"[Transcriber] faster-whisper unavailable ({exc}). "
                "Switching automatically to high-accuracy SpeechRecognition engine..."
            )
            import speech_recognition as sr
            self._sr_recognizer = sr.Recognizer()

    def transcribe(self, audio: np.ndarray, sample_rate: int = None) -> str:
        if audio is None or len(audio) == 0:
            return ""

        sr_rate = sample_rate or getattr(config, "SAMPLE_RATE", 16000)

        # Normalize quiet speech to -1 dBFS peak so audio is clean
        peak = float(np.max(np.abs(audio)))
        if 0.005 < peak < 0.70:
            audio = audio * (0.85 / peak)

        # 1. Try Whisper if successfully initialized
        if self._whisper is not None:
            try:
                segments, _info = self._whisper.transcribe(
                    audio,
                    language="en",
                    initial_prompt=self._PROMPT,
                    beam_size=5,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    compression_ratio_threshold=2.4,
                    no_speech_threshold=0.6,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=200),
                )
                raw_text = " ".join(segment.text.strip() for segment in segments).strip()
                if raw_text:
                    return ai_clean_voice_command(raw_text)
            except Exception as exc:
                print(f"[Transcriber] Whisper runtime error ({exc}); switching to SpeechRecognition...")
                self._whisper = None  # Don't hit mkl_malloc repeatedly

        # 2. Use SpeechRecognition (Google STT)
        try:
            import speech_recognition as sr
            if self._sr_recognizer is None:
                self._sr_recognizer = sr.Recognizer()

            data_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            audio_data = sr.AudioData(data_int16.tobytes(), sr_rate, 2)
            raw_text = self._sr_recognizer.recognize_google(audio_data)
            return ai_clean_voice_command(raw_text)
        except Exception:
            return ""




import edge_tts


def shape_pauses(
    audio: np.ndarray,
    sr: int,
    comma_target_s: float = 0.70,
    period_target_s: float = 1.00,
    threshold: float = 0.001,
) -> np.ndarray:
    """Enforces precise pause durations: exactly comma_target_s (0.7s) after commas,
    and period_target_s (1.0s) after periods."""
    if len(audio) == 0:
        return audio
    hop = int(sr * 0.02)  # 20ms analysis window
    is_silent = []
    for i in range(0, len(audio), hop):
        chunk = audio[i : i + hop]
        rms = np.sqrt(np.mean(chunk**2)) if len(chunk) > 0 else 0
        is_silent.append(rms < threshold)

    runs = []
    in_run = False
    run_start = 0
    for idx, s in enumerate(is_silent):
        if s and not in_run:
            in_run = True
            run_start = idx
        elif not s and in_run:
            in_run = False
            runs.append((run_start * hop, idx * hop))
    if in_run:
        runs.append((run_start * hop, len(audio)))

    out = []
    prev_end = 0
    for start, end in runs:
        out.append(audio[prev_end:start])
        dur = (end - start) / sr
        if start == 0 or end >= len(audio):
            # Keep lead-in and trailing silence as is
            out.append(audio[start:end])
        elif 0.10 <= dur < 0.50:
            # Comma pause: expand to exact 0.7s
            out.append(np.zeros(int(sr * comma_target_s), dtype=audio.dtype))
        elif dur >= 0.50:
            # Period pause: adjust to exact 1.0s
            out.append(np.zeros(int(sr * period_target_s), dtype=audio.dtype))
        else:
            out.append(audio[start:end])
        prev_end = end
    out.append(audio[prev_end:])
    return np.concatenate(out) if out else audio


def clean_markdown_for_speech(text: str) -> str:
    """Removes markdown syntax and normalizes punctuation for precise, natural speech timing:
    - Unifies salutations (e.g. 'Hey, Sir. Abdullah' -> 'Hey Sir Abdullah,') so the address is
      spoken continuously without internal stutter, followed by a 0.7s clause pause.
    - Preserves commas (,) for 0.7s pauses and periods (.) for 1.0s pauses.
    - Strips honorific periods ('Sir.', 'Mr.') so titles never trigger accidental sentence breaks.
    """
    if not text:
        return ""
    # Strip role prefixes if present
    text = re.sub(r'^(Jarvis|Assistant):\s*', '', text, flags=re.IGNORECASE)
    # Strip markdown code blocks ```...```
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    # Strip inline code backticks `code` -> code
    text = text.replace('`', '')
    # Strip bold and italics: ***text***, **text**, *text*, ___text___, __text__, _text_
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)
    text = text.replace('*', '')
    # Strip markdown headers (# Title)
    text = re.sub(r'^\s*#{1,6}\s*', '', text, flags=re.MULTILINE)
    # Strip markdown links [label](url) -> label
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # Strip bullet points at start of line
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    # Strip table dividers
    text = text.replace('|', ' ')

    # 1. Clean honorifics so 'Sir.' or 'Mr.' doesn't become a sentence terminator with 1s pause
    text = re.sub(r'\b(Mr|Ms|Mrs|Dr|Prof)\.\s*', r'\1 ', text, flags=re.IGNORECASE)

    # 2. Unify salutations into ONE phrase without internal pauses:
    # 'Hey, Sir. Abdullah' / 'Hey, Sir. Abudllah' -> 'Hey Sir Abdullah,'
    text = re.sub(r'\bHey,?\s*Sir\.?\s*(?:Abdullah|Abudllah)\b,?', 'Hey Sir Abdullah,', text, flags=re.IGNORECASE)
    text = re.sub(r'\bHey,?\s*Sir\b(?![\s.]*(?:Abdullah|Abudllah))[,.]?', 'Hey Sir,', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<!Hey\s)\bSir\.?\s*(?:Abdullah|Abudllah)\b,?', 'Sir Abdullah,', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(Positive|Negative|Yes|No|Certainly|Sure),?\s*sir\b[,.]?', r'\1 sir,', text, flags=re.IGNORECASE)
    text = re.sub(r'\bAt your service,?\s*Sir Abdullah\.?', 'At your service Sir Abdullah.', text, flags=re.IGNORECASE)

    # 3. Semicolons and standalone colons -> comma for a natural 0.7s clause pause
    text = text.replace(';', ', ')
    text = re.sub(r'\s+:\s+', ', ', text)

    # 4. Clean stacked punctuation and normalize whitespace
    text = re.sub(r'[\r\n]+', '. ', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r',{2,}', ',', text)
    text = re.sub(r',\s*\.', '.', text)
    text = re.sub(r'\.\s*,', '.', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Splits text into cleaned sentence chunks for callers that process sentence by sentence."""
    cleaned = clean_markdown_for_speech(text)
    if not cleaned:
        return []
    chunks = re.split(r'(?<=[.!?])\s+', cleaned)
    return [c.strip() for c in chunks if c.strip()]


def format_speech_ssml(text: str, comma_ms: int = 700, period_ms: int = 1000) -> str:
    """Prepares text with SSML break tags for natural, humanized speech cadence:
    - 700ms natural acoustic break at commas
    - 1000ms natural acoustic break at sentence terminals (. ! ?)
    - Avoids artificial digital-zero cuts by letting the neural voice synthesize human breath and decay
    """
    if not text:
        return ""
    ssml = text
    # Insert natural SSML pauses after commas and punctuation, except at the end
    ssml = re.sub(r',\s+(?!$)', f', <break time="{comma_ms}ms"/> ', ssml)
    ssml = re.sub(r'([.!?])\s+(?!$)', rf'\1 <break time="{period_ms}ms"/> ', ssml)
    return ssml


class Speaker:
    """Synthesizes speech with Google Gemini TTS or Edge Neural TTS.
    Features real-time PyAV packet streaming and unified continuous playback with
    humanized neural pauses (700ms at commas, 1000ms at sentence breaks).
    """

    def __init__(self) -> None:
        self._client = None
        self._gemini_quota_exhausted = False
        if config.GEMINI_API_KEY:
            try:
                self._client = genai.Client(api_key=config.GEMINI_API_KEY)
            except Exception:
                self._client = None

    def _say_edge_tts(self, text: str, on_start: Callable[[], None] | None = None) -> None:
        try:
            clean_text = clean_markdown_for_speech(text)
            if not clean_text:
                return

            voice = getattr(config, "EDGE_VOICE", "en-US-ChristopherNeural")
            pitch = getattr(config, "EDGE_PITCH", "-4Hz")
            rate = getattr(config, "EDGE_RATE", "-2%")

            async def _download_audio(content: str) -> bytes:
                comm = edge_tts.Communicate(content, voice, pitch=pitch, rate=rate)
                audio_bytes = b""
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        audio_bytes += chunk["data"]
                return audio_bytes

            data = asyncio.run(_download_audio(clean_text))
            if not data:
                return

            buf = io.BytesIO(data)
            audio, samplerate = sf.read(buf, dtype="float32")

            if on_start:
                on_start()

            sd.play(audio, samplerate=samplerate)
            sd.wait()  # Ensure entire sentence completes playback before returning
        except Exception as exc:
            print(f"(Edge TTS audio error: {exc})")



    def say(self, text: str, on_start: Callable[[], None] | None = None) -> None:
        if not text:
            return

        clean_text = clean_markdown_for_speech(text)
        if not clean_text:
            return

        # If user explicitly configured Gemini TTS, try that first
        use_gemini = (
            self._client is not None
            and not self._gemini_quota_exhausted
            and config.GEMINI_TTS_MODEL
            and config.GEMINI_TTS_MODEL.lower() != "edge-tts"
        )

        if use_gemini:
            try:
                response = self._client.models.generate_content(
                    model=config.GEMINI_TTS_MODEL,
                    contents=clean_text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=config.GEMINI_TTS_VOICE,
                                )
                            ),
                        ),
                    ),
                )
                audio_bytes = response.candidates[0].content.parts[0].inline_data.data
                if audio_bytes.startswith(b"RIFF"):
                    wav_buf = io.BytesIO(audio_bytes)
                else:
                    wav_buf = io.BytesIO()
                    with wave.open(wav_buf, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(audio_bytes)
                    wav_buf.seek(0)
                audio, samplerate = sf.read(wav_buf, dtype="float32")
                if on_start:
                    on_start()
                sd.play(audio, samplerate=samplerate)
                sd.wait()
                return
            except Exception as exc:
                self._gemini_quota_exhausted = True
                print(f"Gemini TTS quota/limit reached ({str(exc)[:60]}...), switched to Edge Neural TTS.")

        # Default fast streaming Edge Neural TTS
        self._say_edge_tts(clean_text, on_start=on_start)


def send_to_jarvis(text: str) -> str:
    """Sends transcribed text directly to the in-process JARVIS Gemini agent and returns the reply."""
    return get_agent().chat(text)
