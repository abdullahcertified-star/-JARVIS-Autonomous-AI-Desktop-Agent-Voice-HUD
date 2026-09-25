"""Tests for Bilingual (English & Urdu / Roman Urdu / Hinglish) voice and agent intelligence."""
from unittest.mock import patch
import pytest

from agent import check_fast_path
from voice.pipeline import detect_voice_for_text, enforce_status_prefix
from voice import config


class TestVoiceAutoSwitch:
    """Verifies that TTS dynamically and accurately switches between
    Christopher (English) and Asad (Urdu / Roman Urdu / Hinglish)."""

    def test_english_voice_selected(self) -> None:
        voice, pitch, rate = detect_voice_for_text("Positive sir, Google Chrome has been launched.")
        assert voice == "en-US-ChristopherNeural"
        assert pitch == "-4Hz"
        assert rate == "-2%"

    def test_english_wake_status_selected(self) -> None:
        voice, _, _ = detect_voice_for_text("Sir Abdullah, I am awake and all systems are fully operational.")
        assert voice == "en-US-ChristopherNeural"

    def test_roman_urdu_selected(self) -> None:
        voice, pitch, rate = detect_voice_for_text("Jee Sir Abdullah, volume barha diya gaya hai.")
        assert voice == "ur-PK-AsadNeural"
        assert pitch == "+0Hz"
        assert rate == "+0%"

    def test_roman_urdu_greeting_selected(self) -> None:
        voice, _, _ = detect_voice_for_text("Jee Sir Abdullah, main theek hoon aur all systems fully operational hain.")
        assert voice == "ur-PK-AsadNeural"

    def test_nastaliq_urdu_script_selected(self) -> None:
        voice, pitch, rate = detect_voice_for_text("جی سر عبداللہ، تمام سسٹمز فعال ہیں۔")
        assert voice == "ur-PK-AsadNeural"
        assert pitch == "+0Hz"
        assert rate == "+0%"


class TestBilingualStatusPrefix:
    """Ensures enforce_status_prefix preserves Urdu polite greetings while
    still enforcing 'Positive sir,' on English outputs."""

    def test_english_reply_gets_prefix(self) -> None:
        res = enforce_status_prefix("opened Drive C in File Explorer.")
        assert res.startswith("Positive sir,")

    def test_english_with_existing_prefix(self) -> None:
        res = enforce_status_prefix("Positive sir, task complete.")
        assert res == "Positive sir, task complete."

    def test_roman_urdu_greeting_preserved(self) -> None:
        res = enforce_status_prefix("Jee Sir Abdullah, main theek hoon.")
        assert res == "Jee Sir Abdullah, main theek hoon."

    def test_nastaliq_urdu_greeting_preserved(self) -> None:
        res = enforce_status_prefix("جی سر عبداللہ، تمام سسٹمز فعال ہیں۔")
        assert res == "جی سر عبداللہ، تمام سسٹمز فعال ہیں۔"

    def test_nastaliq_urdu_without_prefix_gets_urdu_prefix(self) -> None:
        res = enforce_status_prefix("تمام سسٹمز فعال ہیں۔")
        assert res.startswith("جی سر عبداللہ،")


class TestBilingualFastPaths:
    """Verifies that check_fast_path provides 0ms responses for common Urdu commands."""

    def test_urdu_greetings(self) -> None:
        res1 = check_fast_path("kya haal hai")
        assert res1 is not None
        assert "Jee Sir Abdullah" in res1
        assert "theek" in res1

        res2 = check_fast_path("kaise ho jarvis")
        assert res2 is not None
        assert "Jee Sir Abdullah" in res2

        res3 = check_fast_path("tum kaun ho")
        assert res3 is not None
        assert "JARVIS" in res3

    def test_urdu_time_and_date(self) -> None:
        res_time = check_fast_path("kya time hai")
        assert res_time is not None
        assert "Jee Sir Abdullah, is waqt" in res_time

        res_waqt = check_fast_path("waqt batao")
        assert res_waqt is not None
        assert "Jee Sir Abdullah, is waqt" in res_waqt

        res_date = check_fast_path("aaj kya tareekh hai")
        assert res_date is not None
        assert "Jee Sir Abdullah, aaj" in res_date

    @patch("actions.system.volume_up")
    def test_urdu_volume_up(self, mock_vol_up) -> None:
        res = check_fast_path("awaz barhao")
        assert res is not None
        assert "volume barha diya" in res
        mock_vol_up.assert_called_once()

    @patch("actions.system.volume_down")
    def test_urdu_volume_down(self, mock_vol_down) -> None:
        res = check_fast_path("awaz kam karo")
        assert res is not None
        assert "volume kam kar diya" in res
        mock_vol_down.assert_called_once()

    @patch("actions.system.volume_mute")
    def test_urdu_volume_mute(self, mock_mute) -> None:
        res = check_fast_path("awaz band karo")
        assert res is not None
        assert "audio mute" in res
        mock_mute.assert_called_once()

    @patch("actions.system._empty_recycle_bin")
    def test_urdu_recycle_bin(self, mock_empty) -> None:
        res = check_fast_path("recycle bin saaf karo")
        assert res is not None
        assert "Recycle Bin saaf" in res
        mock_empty.assert_called_once()

    def test_english_commands_unaffected(self) -> None:
        """Confirms English fast paths continue to return 'Positive sir,'."""
        res_hello = check_fast_path("hello jarvis")
        assert res_hello == "At your service, Sir Abdullah. How may I assist you?"

        res_wake = check_fast_path("wake up")
        assert res_wake == "Sir Abdullah, I am awake and all systems are fully operational."

        res_who = check_fast_path("who are you")
        assert res_who == "I am JARVIS, your personal desktop automation AI assistant."
