"""Tests for Cinematic SFX and Voice Interruption (Barge-In) engine."""

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from voice.barge_in import BargeInMonitor
from voice.pipeline import Speaker
from voice.sfx import SoundEffects, get_sfx


def test_sfx_singleton_and_cache():
    sfx = get_sfx()
    assert sfx is not None
    assert isinstance(sfx, SoundEffects)

    # Verify standard sound files are cached
    expected_sounds = {"wake", "listening_end", "positive", "negative", "standby", "shutdown"}
    for sound in expected_sounds:
        assert sound in sfx._cache, f"Sound '{sound}' should be cached in memory"
        data, sr = sfx._cache[sound]
        assert sr == 44100
        assert isinstance(data, np.ndarray)
        assert len(data) > 0


def test_sfx_playback_methods_nonblocking():
    sfx = get_sfx()
    with patch("sounddevice.play") as mock_play:
        sfx.play_wake()
        sfx.play_listening_end()
        sfx.play_positive()
        sfx.play_negative()
        sfx.play_standby()
        sfx.play_shutdown()
        # Give threads a tiny instant to execute
        time.sleep(0.05)
        assert mock_play.call_count >= 1


def test_barge_in_monitor_lifecycle():
    interrupt_event = threading.Event()
    monitor = BargeInMonitor(interrupt_event)

    assert not monitor.interrupted
    assert not interrupt_event.is_set()

    with monitor:
        assert monitor._thread is not None
        assert monitor._thread.is_alive()

    # Exited context manager
    assert monitor._stop_event.is_set()


def test_barge_in_detects_loud_voice():
    interrupt_event = threading.Event()
    monitor = BargeInMonitor(interrupt_event)

    # Mock open_input_stream to return loud frames simulating user talking
    mock_stream = MagicMock()
    # 800 samples of loud signal
    loud_frame = (np.ones((800, 1), dtype=np.int16) * 3000)
    mock_stream.read.return_value = (loud_frame, False)

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_stream
    mock_stream_ctx.__exit__.return_value = None

    with patch("voice.barge_in.open_input_stream", return_value=mock_stream_ctx), \
         patch("voice.barge_in.getattr") as mock_getattr, \
         patch("sounddevice.stop") as mock_sd_stop:
        
        # Set grace period to 0.0 for immediate test triggering
        def fake_getattr(obj, name, default=None):
            if name == "BARGE_IN_GRACE_PERIOD_SEC":
                return 0.0
            if name == "BARGE_IN_ENERGY_RATIO":
                return 1.5
            if name == "BARGE_IN_ENABLED":
                return True
            return getattr(obj, name, default)

        mock_getattr.side_effect = fake_getattr

        monitor.start()
        # Wait up to 300ms for detection thread to trigger
        interrupt_event.wait(timeout=0.3)
        monitor.stop()

        assert monitor.interrupted is True
        assert interrupt_event.is_set() is True
        assert mock_sd_stop.called


def test_speaker_say_interruption():
    speaker = Speaker()
    interrupt_event = threading.Event()

    # Generate 1 second of dummy float32 audio
    audio = np.zeros(16000, dtype=np.float32)

    with patch("sounddevice.play"), patch("sounddevice.stop") as mock_stop:
        # Pre-set interruption event
        interrupt_event.set()
        interrupted = speaker._play_audio_stream(
            audio,
            samplerate=16000,
            interrupt_event=interrupt_event,
        )

        assert interrupted is True
        assert mock_stop.called
