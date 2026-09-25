"""Voice client entry point: say "Hey Jarvis", speak your request, hear the
reply -- with a floating JARVIS-style interface showing the conversation.

Loop: listen for the wake word -> record until you stop talking ->
transcribe -> send the text to your existing n8n Jarvis chat webhook ->
speak the reply out loud. Runs until the orb window is closed.

The native GUI event loop must own the main thread, so the voice loop itself
runs on a background thread started by JarvisWindow.start(). Background
threads never receive Ctrl+C in Python -- only the main thread does -- so
shutdown is driven by a stop_event set when the orb window closes, checked
periodically inside the audio loops (see voice/audio.py's StopRequested).

Run with:
    .venv\\Scripts\\python -m voice.main
"""

from __future__ import annotations

import re
import threading
import time

from voice import config
from voice.audio import (
    StopRequested,
    WakeWordListener,
    adjust_for_ambient_noise,
    record_until_silence,
)
from voice.barge_in import BargeInMonitor
from voice.pipeline import (
    Speaker,
    Transcriber,
    classify_reply,
    enforce_status_prefix,
    send_to_jarvis,
)
from voice.sfx import get_sfx
from voice.ui import JarvisWindow

_GREETING = "At your service, Sir Abdullah."


def _speak_with_barge_in(
    text: str,
    window: JarvisWindow,
    speaker: Speaker,
) -> bool:
    """Speaks the response while monitoring for user barge-in interruptions.
    Returns True if user interrupted playback, False otherwise.
    """
    interrupt_event = threading.Event()
    barge_in = BargeInMonitor(interrupt_event)
    window.set_state("speaking")
    interrupted = False
    try:
        with barge_in:
            interrupted = speaker.say(text, interrupt_event=interrupt_event)
    except Exception as exc:
        print(f"(playback error: {exc})")
    return interrupted


def _process_and_reply(text: str, window: JarvisWindow, speaker: Speaker) -> bool:
    """Dispatches a recognized command to Jarvis, enforces the Positive/Negative protocol,
    plays cinematic SFX, and speaks the reply out loud with barge-in support.
    Returns True if interrupted by user voice, False otherwise."""
    sfx = get_sfx()
    clean_token = re.sub(r'[^a-z]', '', text.lower())
    if clean_token in ("heyjarvis", "jarvis", "hellojarvis", "heythere", "wakeup", "wakeupjarvis", "jarviswakeup", "areyouthere", "areyouawake", "online"):
        reply = "At your service, Sir Abdullah. How may I assist you?"
    else:
        try:
            raw_reply = send_to_jarvis(text)
            reply = enforce_status_prefix(raw_reply)
        except Exception as exc:  # noqa: BLE001
            print(f"(error talking to Jarvis: {exc})")
            sfx.play_negative()
            window.set_state("error")
            error_msg = "Negative sir, I couldn't reach the agent just now."
            window.add_message("jarvis", error_msg, "negative")
            _speak_with_barge_in(error_msg, window, speaker)
            window.set_state("listening")
            return False

    clean_reply = (reply or "").strip()
    tone = classify_reply(clean_reply)
    spoken_reply = clean_reply if clean_reply else ("Positive sir." if tone == "positive" else "Negative sir.")

    # Play subtle futuristic feedback tone matching response sentiment
    if tone == "positive":
        sfx.play_positive()
    else:
        sfx.play_negative()

    # Immediately show the reply on CLI and in the UI log -- zero visual latency
    print(f"Jarvis: {spoken_reply}")
    window.add_message("jarvis", spoken_reply, tone)

    interrupted = _speak_with_barge_in(spoken_reply, window, speaker)
    if interrupted:
        print("\n[Barge-in] Interrupted by user voice -> immediately listening.")
        sfx.play_wake()
    else:
        # Small cooldown so speaker echo does not re-trigger mic input
        time.sleep(0.3)

    window.set_state("listening")
    return interrupted


def _is_terminate_command(text: str) -> bool:
    clean = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    terminate_phrases = (
        "terminate yourself", "terminate jarvis", "shut down yourself",
        "shutdown yourself", "shutdown jarvis", "shut down jarvis",
        "exit jarvis", "quit jarvis", "close yourself", "close jarvis",
        "kill yourself", "terminate program", "exit program",
        "close the program", "self destruct", "turn yourself off",
        "turn off jarvis"
    )
    if any(p in clean for p in terminate_phrases):
        return True
    words = clean.split()
    if any(w in words for w in ("terminate", "exit", "quit")) and ("yourself" in words or "jarvis" in words or len(words) <= 2):
        return True
    return False


def _handle_voice_meta_command(
    text: str,
    window: JarvisWindow,
    speaker: Speaker,
    stop_event: threading.Event,
) -> bool:
    """Handles meta conversation commands like termination or standby/sleep.
    Returns True if handled (loop should break or exit), False otherwise."""
    sfx = get_sfx()
    clean_lower = text.lower().strip()

    # 1. Termination: "Jarvis terminate yourself", "shutdown jarvis", "exit", etc.
    if _is_terminate_command(clean_lower):
        sfx.play_shutdown()
        farewell = "Positive sir, terminating all processes and shutting down. Goodbye, Sir Abdullah."
        print(f"Jarvis: {farewell}")
        window.add_message("jarvis", farewell, "positive")
        window.set_state("speaking")
        try:
            speaker.say(farewell)
        except Exception:
            pass
        stop_event.set()
        window.close()
        raise StopRequested

    # 2. Standby / Sleep: "go to sleep", "sleep", "stand by", "dismissed", "goodbye", "bye-bye jarvis"
    sleep_triggers = (
        "go to sleep", "sleep", "stand by", "stand down",
        "stop listening", "goodbye", "bye jarvis", "bye-bye jarvis",
        "bye bye jarvis", "sleep jarvis", "dismissed", "shut up",
        "rest now", "take a break"
    )
    if any(trig in clean_lower for trig in sleep_triggers):
        sfx.play_standby()
        standby_msg = "Standing by, Sir Abdullah."
        print(f"Jarvis: {standby_msg}")
        window.add_message("jarvis", standby_msg, "positive")
        _speak_with_barge_in(standby_msg, window, speaker)
        window.set_state("idle")
        return True

    return False



def _voice_loop(window: JarvisWindow, stop_event: threading.Event) -> None:
    wake_word = None
    sfx = get_sfx()
    try:
        window.set_state("thinking")
        print("Loading speech recognition model (first run downloads it)...")
        transcriber = Transcriber()
        speaker = Speaker()
        wake_word = WakeWordListener(stop_event=stop_event, pause_event=window.muted)

        # Initialize JARVIS agent so first query has zero latency
        from agent import get_agent
        get_agent()

        print("Calibrating microphone for ambient background noise...")
        adjust_for_ambient_noise(duration=1.0)

        print('Ready. Say "Hey Jarvis" to talk to Jarvis. Close the orb window to quit.')
        sfx.play_positive()
        window.add_message("jarvis", _GREETING)
        _speak_with_barge_in(_GREETING, window, speaker)
        window.set_state("idle")

        while True:
            # 1. STANDBY: Wait for wake word "Hey Jarvis"
            print('\n[Standby] Waiting for wake word "Hey Jarvis"...')
            window.set_state("idle")
            wake_word.listen()
            sfx.play_wake()
            print('\n[Awake] "Hey Jarvis" detected! Entering active conversation mode...')

            # 2. Check if user already spoke a command right after "Hey Jarvis"
            window.set_state("listening")
            audio = record_until_silence(
                on_level=window.set_level,
                stop_event=stop_event,
                phrase_time_limit=config.MAX_RECORD_SECONDS,
                timeout=config.SPEECH_START_TIMEOUT_SEC,
            )

            # If user said "Hey Jarvis" and paused, greet them
            if audio is None:
                wake_greeting = "At your service, Sir Abdullah. How may I assist you?"
                print(f"Jarvis: {wake_greeting}")
                window.add_message("jarvis", wake_greeting, "positive")
                _speak_with_barge_in(wake_greeting, window, speaker)
                window.set_state("listening")
            else:
                sfx.play_listening_end()
                window.set_state("thinking")
                text = transcriber.transcribe(audio)
                if not text:
                    wake_greeting = "At your service, Sir Abdullah. How may I assist you?"
                    print(f"Jarvis: {wake_greeting}")
                    window.add_message("jarvis", wake_greeting, "positive")
                    _speak_with_barge_in(wake_greeting, window, speaker)
                    window.set_state("listening")
                else:
                    print(f"You: {text}")
                    window.add_message("you", text)
                    if _handle_voice_meta_command(text, window, speaker, stop_event):
                        continue
                    _process_and_reply(text, window, speaker)

            # 3. CONTINUOUS ACTIVE CONVERSATION SESSION (stays awake for 45s)
            while True:
                if stop_event is not None and stop_event.is_set():
                    raise StopRequested

                window.set_state("listening")
                print(f"\n[Active Conversation] Listening for follow-up command (standby timeout: {config.CONVERSATION_TIMEOUT_SEC:.0f}s)...")

                audio = record_until_silence(
                    on_level=window.set_level,
                    stop_event=stop_event,
                    phrase_time_limit=config.MAX_RECORD_SECONDS,
                    timeout=config.CONVERSATION_TIMEOUT_SEC,
                )

                # If no speech was detected within the 45s window, return to standby
                if audio is None:
                    sfx.play_standby()
                    standby_msg = "Standing by, Sir Abdullah."
                    print(f"\n[Timeout] No speech for {config.CONVERSATION_TIMEOUT_SEC:.0f}s. Returning to standby.")
                    print(f"Jarvis: {standby_msg}")
                    window.add_message("jarvis", standby_msg, "positive")
                    _speak_with_barge_in(standby_msg, window, speaker)
                    window.set_state("idle")
                    break  # Break inner loop back to wake_word.listen()!

                sfx.play_listening_end()
                window.set_state("thinking")
                text = transcriber.transcribe(audio)
                if not text:
                    print("(could not make out words, continuing to listen...)")
                    continue

                print(f"You: {text}")
                window.add_message("you", text)

                # Check for termination or sleep commands
                if _handle_voice_meta_command(text, window, speaker, stop_event):
                    break

                # Process the command
                _process_and_reply(text, window, speaker)

    except StopRequested:
        print("\nOrb closed -- stopping.")
    except Exception as exc:
        print(f"\n[Voice Engine] Unexpected error: {exc}")
    finally:
        if wake_word is not None:
            wake_word.close()


def main() -> None:
    stop_event = threading.Event()
    window = JarvisWindow()
    window.on_close(stop_event.set)
    try:
        window.start(_voice_loop, args=(window, stop_event))
    finally:
        stop_event.set()
        import os
        os._exit(0)


if __name__ == "__main__":
    main()
