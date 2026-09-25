"""Comprehensive Real-time Barge-In, VAD, and State Machine tests for JARVIS."""

from collections import deque
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from voice.barge_in import BargeInMonitor
from voice.pipeline import Speaker, Transcriber, clean_markdown_for_speech, split_sentences
from voice.state import ConversationState, StateManager
from voice.vad import SileroVAD


def test_state_manager_transitions_and_callbacks():
    observed = []
    manager = StateManager(on_change=lambda st: observed.append(st))

    assert manager.current == ConversationState.IDLE
    assert manager.generation_id == 0

    # Transitions
    assert manager.transition_to(ConversationState.LISTENING) is True
    assert manager.current == ConversationState.LISTENING
    assert observed == [ConversationState.LISTENING]

    # No-op same state
    assert manager.transition_to(ConversationState.LISTENING) is False
    assert len(observed) == 1

    # Transition to THINKING, SPEAKING, INTERRUPTED
    manager.transition_to(ConversationState.THINKING)
    manager.transition_to(ConversationState.SPEAKING)
    manager.transition_to(ConversationState.INTERRUPTED)
    assert manager.current == ConversationState.INTERRUPTED
    assert observed[-1] == ConversationState.INTERRUPTED


def test_state_manager_generation_cancellation():
    manager = StateManager()

    gen_1, cancel_1 = manager.new_generation()
    assert gen_1 == 1
    assert not manager.is_generation_cancelled(gen_1)

    # Cancel gen 1
    manager.cancel_generation(gen_1)
    assert cancel_1.is_set()
    assert manager.is_generation_cancelled(gen_1)

    # New generation supersedes gen 1
    gen_2, cancel_2 = manager.new_generation()
    assert gen_2 == 2
    assert not cancel_2.is_set()
    assert not manager.is_generation_cancelled(gen_2)
    # Gen 1 is automatically considered cancelled because current generation_id is 2
    assert manager.is_generation_cancelled(gen_1)


def test_silero_vad_silence_evaluation():
    vad = SileroVAD()
    # 512 samples of digital zero at 16kHz
    silent_frame = np.zeros(512, dtype=np.int16)

    is_voice, prob, rms = vad.evaluate_frame(silent_frame, is_speaking=False)
    assert is_voice is False
    assert prob < 0.10
    assert rms == 0.0


def test_silero_vad_echo_suppression_during_speech():
    vad = SileroVAD()
    # Mock model probability to simulate borderline speaker bleed
    vad._model = MagicMock()
    # Return 0.60 probability (below 0.75 barge-in threshold)
    vad._model.return_value = [0.60]

    frame = (np.random.randn(512) * 200).astype(np.int16)
    is_voice, prob, rms = vad.evaluate_frame(
        frame,
        is_speaking=True,
        echo_floor_rms=500.0,
    )
    # Speaker bleed below threshold must NOT interrupt
    assert is_voice is False
    assert prob == 0.60


def test_silero_vad_genuine_user_voice_during_speech():
    vad = SileroVAD()
    vad._model = MagicMock()
    # Return 0.92 probability (above 0.75 barge-in threshold)
    vad._model.return_value = [0.92]

    # High energy user voice frame above speaker floor
    frame = (np.random.randn(512) * 1500).astype(np.int16)
    is_voice, prob, rms = vad.evaluate_frame(
        frame,
        is_speaking=True,
        echo_floor_rms=300.0,
    )
    # Genuine loud voice while speaking triggers interruption
    assert is_voice is True
    assert prob == 0.92


def test_barge_in_monitor_instant_cutoff_and_handoff():
    interrupt_event = threading.Event()
    mock_vad = MagicMock()
    # 1st call: speech (evaluates during speaking)
    # Subsequent calls: silence (evaluates during interruption capture remainder)
    mock_vad.evaluate_frame.side_effect = [
        (True, 0.95, 2500.0),   # frame 1
        (True, 0.95, 2500.0),   # frame 2 -> triggers interruption cutoff
        (False, 0.05, 50.0),    # silence in remainder
        (False, 0.05, 50.0),    # silence in remainder
        (False, 0.05, 50.0),    # silence in remainder
    ]

    mock_on_interrupt = MagicMock()
    monitor = BargeInMonitor(
        interrupt_event=interrupt_event,
        on_interrupt=mock_on_interrupt,
        vad=mock_vad,
    )

    mock_stream = MagicMock()
    dummy_frame = (np.ones((512, 1), dtype=np.int16) * 1500)
    mock_stream.read.return_value = (dummy_frame, False)

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_stream
    mock_stream_ctx.__exit__.return_value = None

    with patch("voice.barge_in.open_input_stream", return_value=mock_stream_ctx), \
         patch("voice.barge_in.getattr") as mock_getattr, \
         patch("sounddevice.stop") as mock_sd_stop:

        def fake_getattr(obj, name, default=None):
            if name == "BARGE_IN_GRACE_PERIOD_SEC":
                return 0.0
            if name == "BARGE_IN_ENABLED":
                return True
            if name == "VAD_SILENCE_DURATION_SEC":
                return 0.05  # quick silence cutoff for test
            return getattr(obj, name, default)

        mock_getattr.side_effect = fake_getattr

        monitor.start()
        interrupt_event.wait(timeout=0.5)
        monitor.stop()

        assert monitor.interrupted is True
        assert interrupt_event.is_set() is True
        assert mock_sd_stop.called
        assert mock_on_interrupt.called
        # Check audio handoff captured remainder
        assert monitor.captured_audio is not None
        assert isinstance(monitor.captured_audio, np.ndarray)


def test_split_sentences_and_markdown_cleaning():
    text = "Hey, Sir. Abdullah! How are you doing? Let's write some `asyncio` code. Affirmative sir."
    sentences = split_sentences(text)
    assert len(sentences) >= 3
    # Verify honorific and salutation cleanup
    assert any("Hey Sir Abdullah" in s for s in sentences)
    assert all("`" not in s for s in sentences)


def test_speaker_streaming_sentence_interruption():
    speaker = Speaker()
    interrupt_event = threading.Event()

    long_text = "First sentence of the reply. Second sentence that should be interrupted. Third sentence that must never play."

    # Simulate interruption during the first sentence
    call_counts = {"play": 0}

    def fake_play_audio(audio, samplerate, interrupt_event=None, on_start=None):
        call_counts["play"] += 1
        if interrupt_event is not None:
            # Set interruption immediately during first sentence playback
            interrupt_event.set()
            speaker.interrupt()
            return True
        return False

    with patch.object(speaker, "_play_audio_stream", side_effect=fake_play_audio), \
         patch("sounddevice.stop") as mock_stop:

        interrupted = speaker._say_edge_tts(long_text, interrupt_event=interrupt_event)

        assert interrupted is True
        assert mock_stop.called
        # Crucial: Must stop immediately and not continue to sentence 2 or 3!
        assert call_counts["play"] == 1


def test_transcriber_prompt_contains_multilingual_context():
    # Verify English, Urdu, and Roman Urdu keywords are present in Whisper initial prompt
    prompt = Transcriber._PROMPT.lower()
    assert "jarvis" in prompt
    assert "sir abdullah" in prompt
    assert "karo" in prompt
    assert "batao" in prompt
    assert "roman urdu" in prompt
    assert "urdu" in prompt
