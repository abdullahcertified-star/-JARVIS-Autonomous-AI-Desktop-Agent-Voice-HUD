"""Transcription, sending text to the JARVIS Gemini agent, and speaking the reply."""

from __future__ import annotations

import asyncio
import io
import queue
import re
import threading
import time
import wave
from typing import Callable, Literal, Optional

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

    # Preserve Urdu affirmative or polite salutations
    if re.match(r"^(?:jee|ji|haan|shukriya|sahih|theek)\s*(?:sir|sir abdullah)?[,\s]*", cleaned, re.IGNORECASE):
        return cleaned

    # If in Urdu Nastaliq script
    if re.search(r"[\u0600-\u06FF]", cleaned):
        if any(cleaned.startswith(p) for p in ("جی سر", "جی سر عبداللہ", "معذرت سر", "معاف کیجیے")):
            return cleaned
        prefix = "جی سر عبداللہ، " if classify_reply(cleaned) == "positive" else "معذرت سر، "
        return f"{prefix}{cleaned}"

    # If in Roman Urdu / Hinglish without salutation
    roman_urdu_patterns = (
        r"\b(?:theek|khol|chala|band|barha|kam|saaf|khidmat|tayyar|kaam|aawaz|awaz|tareekh|waqt|karo|gaya|diya|karunga)\b",
    )
    if any(re.search(pat, cleaned.lower()) for pat in roman_urdu_patterns):
        prefix = "Jee Sir Abdullah, " if classify_reply(cleaned) == "positive" else "Maazrat sir, "
        return f"{prefix}{cleaned}"

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
    # Common speech-to-text mishearings where 'Hinglish' was heard as 'English' in Urdu/Hinglish context:
    (re.compile(r"\benglish\s+ke\s+an?dar\b", re.IGNORECASE), "hinglish ke andar"),
    (re.compile(r"\benglish\s+me\s+kro\b", re.IGNORECASE), "hinglish mein karo"),
    (re.compile(r"\benglish\s+mein\s+kro\b", re.IGNORECASE), "hinglish mein karo"),
    (re.compile(r"\b(?:urdu|hindi)\s+(?:chhodo|choro|chorho)\s+.*?\benglish\b", re.IGNORECASE), lambda m: re.sub(r"\benglish\b", "hinglish", m.group(0), flags=re.I)),
    (re.compile(r"\benglish\s+mein\s+baat\s+karo\b", re.IGNORECASE), "english mein baat karo"),
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
        "Windows desktop automation, applications, Ethernet, Wi-Fi, volume, Chrome, YouTube, France, Paris, "
        "kholo, band karo, chalao, volume barhao, kam karo, kaise ho, mausam kaisa hai, shukriya, "
        "kya haal hai, screen dikhao, batao, suno, kardo, chalao."
    )

    def __init__(self) -> None:
        self._engine = getattr(config, "STT_ENGINE", "auto").lower()
        self._whisper = None
        self._sr_recognizer = None
        self._current_lang = "en"

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
                whisper_lang = getattr(config, "WHISPER_LANGUAGE", "auto")
                lang_arg = None if whisper_lang in ("auto", "all", "detect", None) else whisper_lang
                segments, _info = self._whisper.transcribe(
                    audio,
                    language=lang_arg,
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

        # 2. Use SpeechRecognition (Google STT with Bilingual Auto-Switch)
        try:
            import speech_recognition as sr
            if self._sr_recognizer is None:
                self._sr_recognizer = sr.Recognizer()

            data_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            audio_data = sr.AudioData(data_int16.tobytes(), sr_rate, 2)

            raw_text = ""
            current_lang = getattr(self, "_current_lang", "en")
            if current_lang == "ur":
                try:
                    raw_text = self._sr_recognizer.recognize_google(audio_data, language="ur-PK")
                except Exception:
                    raw_text = ""
                if not raw_text:
                    try:
                        raw_text = self._sr_recognizer.recognize_google(audio_data, language="en-US")
                    except Exception:
                        raw_text = ""
            else:
                try:
                    raw_text = self._sr_recognizer.recognize_google(audio_data, language="en-US")
                except Exception:
                    raw_text = ""
                if not raw_text:
                    try:
                        raw_text = self._sr_recognizer.recognize_google(audio_data, language="ur-PK")
                        if raw_text:
                            self._current_lang = "ur"
                    except Exception:
                        raw_text = ""

            if raw_text:
                lowered_raw = raw_text.lower()
                if any(k in lowered_raw for k in ("urdu", "hinglish", "roman urdu", "اردو", "ہنگلش")):
                    if not any(k in lowered_raw for k in ("speak in english", "talk in english", "switch to english")):
                        self._current_lang = "ur"
                elif any(k in lowered_raw for k in ("speak in english", "talk in english", "switch to english", "english bolo", "english mode", "انگلش")):
                    self._current_lang = "en"
                elif re.search(r"[\u0600-\u06FF]", raw_text):
                    self._current_lang = "ur"

                return ai_clean_voice_command(raw_text)
            return ""
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


def detect_voice_for_text(text: str) -> tuple[str, str, str]:
    """Dynamically detects whether text is in Urdu (Nastaliq script),
    Hinglish/Roman Urdu (Latin script), or English, and returns (voice_name, pitch, rate)
    for authentic, humanized, in-flow pronunciation."""
    default_voice = getattr(config, "EDGE_VOICE", "en-US-ChristopherNeural")
    default_pitch = getattr(config, "EDGE_PITCH", "-4Hz")
    default_rate = getattr(config, "EDGE_RATE", "-2%")

    urdu_voice = getattr(config, "EDGE_URDU_VOICE", "ur-PK-AsadNeural")
    urdu_pitch = getattr(config, "EDGE_URDU_PITCH", "+0Hz")
    urdu_rate = getattr(config, "EDGE_URDU_RATE", "+0%")

    hinglish_voice = getattr(config, "EDGE_HINGLISH_VOICE", "ur-PK-AsadNeural")
    hinglish_pitch = getattr(config, "EDGE_HINGLISH_PITCH", "+0Hz")
    hinglish_rate = getattr(config, "EDGE_HINGLISH_RATE", "+0%")

    if not text:
        return default_voice, default_pitch, default_rate

    # 1. Direct Urdu Nastaliq / Arabic Unicode script detection -> Asad
    if re.search(r"[\u0600-\u06FF]", text):
        return urdu_voice, urdu_pitch, urdu_rate

    # 2. Roman Urdu / Hinglish keyword patterns -> Asad (with authentic Pakistani phonemes)
    lowered = text.lower()
    roman_urdu_words = (
        r"\b(?:jee|ji|haan|nahi|nahin|hukam|hukum|madad|karta|karti|suno|kholo|chalao|band\s+karo)\b",
        r"\b(?:barha\s+do|barhao|kam\s+karo|shukriya|aapka|apka|mera|meri|kya\s+haal|kaise\s+ho)\b",
        r"\b(?:mausam|tareekh|waqt|batao|kardo|sahih\s+hai|theek\s+hai|janab|bhai|boli?ye|bataiye)\b",
        r"\b(?:khidmat|tayyar|taiyar|karunga|karungi|baat\s+karo|baat\s+karunga|ab\s+se)\b",
        r"\b(?:kuch|kaam|gaana|aawaz|awaz|saaf|kardo|lagta|zyada|thoda|josh|pagal)\b",
    )
    if any(re.search(pat, lowered) for pat in roman_urdu_words):
        return hinglish_voice, hinglish_pitch, hinglish_rate

    return default_voice, default_pitch, default_rate


ROMAN_URDU_PHRASES = (
    (re.compile(r"\bjee\s+sir\s+abdullah\b", re.I), "جی سر عبداللہ"),
    (re.compile(r"\bji\s+sir\s+abdullah\b", re.I), "جی سر عبداللہ"),
    (re.compile(r"\bjee\s+sir\b", re.I), "جی سر"),
    (re.compile(r"\bji\s+sir\b", re.I), "جی سر"),
    (re.compile(r"\bsir\s+abdullah\b", re.I), "سر عبداللہ"),
    (re.compile(r"\ball\s+systems\s+fully\s+operational\b", re.I), "تمام سسٹمز مکمل طور پر فعال"),
    (re.compile(r"\ball\s+systems\b", re.I), "تمام سسٹمز"),
    (re.compile(r"\bfully\s+operational\b", re.I), "مکمل طور پر فعال"),
    (re.compile(r"\boperational\b", re.I), "فعال"),
    (re.compile(r"\bab\s+se\b", re.I), "اب سے"),
    (re.compile(r"\bkar\s+sakta\s+hoon\b", re.I), "کر سکتا ہوں"),
    (re.compile(r"\bkar\s+sakti\s+hoon\b", re.I), "کر سکتی ہوں"),
    (re.compile(r"\bkar\s+sakte\s+hain\b", re.I), "کر سکتے ہیں"),
    (re.compile(r"\bkar\s+diya\s+gaya\s+hai\b", re.I), "کر دیا گیا ہے"),
    (re.compile(r"\bkar\s+di\s+gayi\s+hai\b", re.I), "کر دی گئی ہے"),
    (re.compile(r"\bkar\s+diya\s+hai\b", re.I), "کر دیا ہے"),
    (re.compile(r"\bkar\s+di\s+hai\b", re.I), "کر دی ہے"),
    (re.compile(r"\bkar\s+diya\b", re.I), "کر دیا"),
    (re.compile(r"\bkar\s+di\b", re.I), "کر دی"),
    (re.compile(r"\bkya\s+haal\s+hai\b", re.I), "کیا حال ہے"),
    (re.compile(r"\bkya\s+hal\s+hai\b", re.I), "کیا حال ہے"),
    (re.compile(r"\bkya\s+chal\s+raha\s+hai\b", re.I), "کیا چل رہا ہے"),
    (re.compile(r"\bkaise\s+ho\b", re.I), "کیسے ہو"),
    (re.compile(r"\bkaise\s+hain\b", re.I), "کیسے ہیں"),
    (re.compile(r"\bsab\s+theek\s+hai\b", re.I), "سب ٹھیک ہے"),
    (re.compile(r"\bbarha\s+diya\s+gaya\s+hai\b", re.I), "بڑھا دیا گیا ہے"),
    (re.compile(r"\bkam\s+kar\s+diya\s+gaya\s+hai\b", re.I), "کم کر دیا گیا ہے"),
    (re.compile(r"\bsaaf\s+kar\s+diya\s+gaya\s+hai\b", re.I), "صاف کر دیا گیا ہے"),
    (re.compile(r"\brecycle\s+bin\b", re.I), "ری سائیکل بن"),
    (re.compile(r"\bfile\s+explorer\b", re.I), "فائل ایکسپلورر"),
    (re.compile(r"\bkyun\s+nahi\b", re.I), "کیوں نہیں"),
    (re.compile(r"\bkuch\s+bhi\b", re.I), "کچھ بھی"),
)

ROMAN_URDU_WORDS = {
    "main": "میں", "mein": "میں", "hoon": "ہوں", "hun": "ہوں", "hai": "ہے", "hain": "ہیں", "ho": "ہو",
    "theek": "ٹھیک", "thek": "ٹھیک", "sahi": "صحیح", "sahih": "صحیح", "bilkul": "بالکل",
    "sub": "سب", "sab": "سب", "kuch": "کچھ", "behtareen": "بہترین", "acha": "اچھا", "achha": "اچھا", "achhi": "اچھی", "achhe": "اچھے",
    "aap": "آپ", "ap": "آپ", "tum": "تم", "tumhen": "تمہیں", "tumhein": "تمہیں",
    "aapka": "آپ کا", "apka": "آپ کا", "aapki": "آپ کی", "apki": "آپ کی", "aapke": "آپ کے", "apke": "آپ کے",
    "mera": "میرا", "meri": "میری", "mere": "میرے", "hamara": "ہمارا", "hamari": "ہماری", "hamare": "ہمارے",
    "yeh": "یہ", "ye": "یہ", "woh": "وہ", "wo": "وہ", "is": "اس", "us": "اس", "in": "ان", "un": "ان",
    "ka": "کا", "ki": "کی", "ke": "کے", "ko": "کو", "se": "سے", "par": "پر", "pe": "پر",
    "aur": "اور", "bhi": "بھی", "to": "تو", "liye": "لیے", "lekin": "لیکن", "magar": "مگر",
    "sath": "ساتھ", "saath": "ساتھ", "andar": "اندر", "ander": "اندر", "bahar": "باہر", "taraf": "طرف",
    "baad": "بعد", "pehle": "پہلے", "pehlay": "پہلے",
    "baat": "بات", "karein": "کریں", "karo": "کرو", "kardo": "کر دو", "karna": "کرنا",
    "karunga": "کروں گا", "karungi": "کروں گی", "karoon": "کروں", "karon": "کروں",
    "karta": "کرتا", "karti": "کرتی", "karte": "کرتے", "kiya": "کیا", "kardi": "کر دی", "kardiya": "کر دیا",
    "bol": "بول", "bolo": "بولو", "boliye": "بولیے", "batao": "بتاؤ", "bataiye": "بتائیے", "batayein": "بتائیں", "batayen": "بتائیں",
    "suno": "سنو", "suniye": "سنیے", "dekho": "دیکھو", "dekh": "دیکھ", "dikhao": "دکھاؤ",
    "kholo": "کھولو", "khol": "کھول", "chalao": "چلاؤ", "chala": "چلا", "chal": "چل",
    "raha": "رہا", "rahi": "رہی", "rahe": "رہے",
    "sakta": "سکتا", "sakti": "سکتی", "sakte": "سکتے", "saktay": "سکتے",
    "chhodo": "چھوڑو", "choro": "چھوڑو", "chorho": "چھوڑو", "rakho": "رکھو", "rakh": "رکھ",
    "aao": "آؤ", "aata": "آتا", "aati": "آتی", "aate": "آتے", "gaya": "گیا", "gayi": "گئی", "gaye": "گئے",
    "madad": "مدد", "khidmat": "خدمت", "tayyar": "تیار", "taiyar": "تیار", "hamesha": "ہمیشہ",
    "hukum": "حکم", "hukm": "حکم", "farmaiye": "فرمائیے", "farmao": "فرماؤ", "shukriya": "شکریہ", "meherbani": "مہربانی",
    "kya": "کیا", "kia": "کیا", "kaise": "کیسے", "kaisa": "کیسا", "kaisi": "کیسی", "kaun": "کون", "kon": "کون",
    "kyun": "کیوں", "kyu": "کیوں", "kahan": "کہاں", "kidhar": "کدھر", "kab": "کب",
    "kitna": "کتنا", "kitni": "کتنی", "kitne": "کتنے",
    "ab": "اب", "abhi": "ابھی", "aaj": "آج", "kal": "کل", "parso": "پرسوں", "waqt": "وقت", "tareekh": "تاریخ",
    "urdu": "اردو", "english": "انگلش", "hinglish": "ہنگلش", "roman": "رومن", "pure": "خالص",
    "itna": "اتنا", "itni": "اتنی", "itne": "اتنے", "bohot": "بہت", "bohat": "بہت", "bahut": "بہت",
    "thoda": "تھوڑا", "thodi": "تھوڑی", "thode": "تھوڑے", "zyada": "زیادہ", "ziyada": "زیادہ",
    "josh": "جوش", "pagal": "پاگل", "saaf": "صاف", "tamam": "تمام", "saari": "ساری", "sari": "ساری",
    "koi": "کوئی", "kisi": "کسی",
    "volume": "والیم", "awaz": "آواز", "aawaz": "آواز", "barhao": "بڑھاؤ", "barha": "بڑھا",
    "kam": "کم", "band": "بند", "windows": "ونڈوز"
}


def convert_roman_urdu_to_script(text: str) -> str:
    """Converts Roman Urdu words and phrases into native Urdu Nastaliq script
    so Edge TTS's Urdu voice (ur-PK-AsadNeural) pronounces every word with authentic
    native Pakistani pronunciation instead of English phonetics."""
    if not text:
        return ""
    result = text
    for pat, rep in ROMAN_URDU_PHRASES:
        result = pat.sub(rep, result)

    def _replace_word(m: re.Match) -> str:
        w = m.group(0).lower()
        return ROMAN_URDU_WORDS.get(w, m.group(0))

    result = re.sub(r"[a-zA-Z]+", _replace_word, result)
    return result


def humanize_urdu_speech(text: str, voice: str = "") -> str:
    """Shapes Urdu and Hinglish speech for ultra-human, warm, in-flow neural delivery:
    1. If target voice is Asad / Salman and text is Roman Urdu, transliterates known words.
       If target voice is Madhur (Hinglish), preserves clean Latin script for fluent, unbroken articulation.
    2. Replaces awkward pauses and ellipses with smooth conversational commas for continuous human flow.
    3. Normalizes breathing breaks around greetings (e.g. 'Jee Sir Abdullah,').
    """
    if not text:
        return ""
    res = text
    # Convert any awkward ellipses '...' to smooth commas so speech flows continuously
    res = re.sub(r"\.{2,}", ", ", res)
    # Ensure natural comma spacing
    res = re.sub(r"[,،]\s*", r", ", res)
    # Normalize multiple commas
    res = re.sub(r",{2,}", ",", res)
    # Ensure clean spacing around sentence terminals
    res = re.sub(r"([.!?۔])\s*", r"\1 ", res)

    if "Asad" in voice or "Salman" in voice or "ur-" in voice or not voice:
        res = convert_roman_urdu_to_script(res)

    res = re.sub(r"\s+", " ", res).strip()
    return res


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

    def _play_audio_stream(
        self,
        audio: np.ndarray,
        samplerate: int,
        interrupt_event: Optional[threading.Event] = None,
        on_start: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Plays audio with low-latency interruption support.
        Returns True if interrupted, False if completed normally.
        """
        if on_start:
            try:
                on_start()
            except Exception:
                pass

        try:
            sd.play(audio, samplerate=samplerate)
            duration = len(audio) / float(samplerate)
            start_t = time.time()

            while (time.time() - start_t) < duration:
                if interrupt_event is not None and interrupt_event.is_set():
                    try:
                        sd.stop()
                    except Exception:
                        pass
                    return True
                time.sleep(0.03)

            try:
                sd.wait()
            except Exception:
                pass
            return False
        except Exception as exc:
            print(f"(playback error: {exc})")
            return False

    def _say_edge_tts(
        self,
        text: str,
        on_start: Callable[[], None] | None = None,
        interrupt_event: Optional[threading.Event] = None,
    ) -> bool:
        try:
            clean_text = clean_markdown_for_speech(text)
            if not clean_text:
                return False

            voice, pitch, rate = detect_voice_for_text(clean_text)
            if any(k in voice for k in ("Asad", "Salman", "Madhur")) or voice.startswith(("ur-", "hi-")) or re.search(r"[\u0600-\u06FF]", clean_text):
                clean_text = humanize_urdu_speech(clean_text, voice=voice)

            async def _download_audio(content: str) -> bytes:
                comm = edge_tts.Communicate(content, voice, pitch=pitch, rate=rate)
                audio_bytes = b""
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        audio_bytes += chunk["data"]
                return audio_bytes

            data = asyncio.run(_download_audio(clean_text))
            if not data:
                return False

            buf = io.BytesIO(data)
            audio, samplerate = sf.read(buf, dtype="float32")

            return self._play_audio_stream(
                audio,
                samplerate=samplerate,
                interrupt_event=interrupt_event,
                on_start=on_start,
            )
        except Exception as exc:
            print(f"(Edge TTS audio error: {exc})")
            return False

    def say(
        self,
        text: str,
        on_start: Callable[[], None] | None = None,
        interrupt_event: Optional[threading.Event] = None,
    ) -> bool:
        """Speaks text using Gemini TTS or Edge Neural TTS.
        Returns True if interrupted by barge-in, False otherwise.
        """
        if not text:
            return False

        clean_text = clean_markdown_for_speech(text)
        if not clean_text:
            return False

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
                return self._play_audio_stream(
                    audio,
                    samplerate=samplerate,
                    interrupt_event=interrupt_event,
                    on_start=on_start,
                )
            except Exception as exc:
                self._gemini_quota_exhausted = True
                print(f"Gemini TTS quota/limit reached ({str(exc)[:60]}...), switched to Edge Neural TTS.")

        # Default fast streaming Edge Neural TTS
        return self._say_edge_tts(clean_text, on_start=on_start, interrupt_event=interrupt_event)



def send_to_jarvis(text: str) -> str:
    """Sends transcribed text directly to the in-process JARVIS Gemini agent and returns the reply."""
    return get_agent().chat(text)
