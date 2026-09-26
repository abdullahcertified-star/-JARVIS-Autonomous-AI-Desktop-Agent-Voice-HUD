"""Tests for Bilingual (English & Urdu / Roman Urdu / Hinglish) voice, pronunciation, and agent intelligence."""
from unittest.mock import patch, MagicMock
import pytest

from agent import check_fast_path
from voice.pipeline import (
    detect_voice_for_text,
    enforce_status_prefix,
    convert_roman_urdu_to_script,
    humanize_urdu_speech,
    Transcriber,
)
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
        assert pitch == "-2Hz"
        assert rate == "-4%"

    def test_roman_urdu_greeting_selected(self) -> None:
        voice, _, _ = detect_voice_for_text("Jee Sir Abdullah, main theek hoon aur all systems fully operational hain.")
        assert voice == "ur-PK-AsadNeural"

    def test_nastaliq_urdu_script_selected(self) -> None:
        voice, pitch, rate = detect_voice_for_text("جی سر عبداللہ، تمام سسٹمز فعال ہیں۔")
        assert voice == "ur-PK-AsadNeural"
        assert pitch == "-2Hz"
        assert rate == "-4%"


class TestRomanToUrduScriptTransliteration:
    """Ensures Roman Urdu is converted into authentic Urdu Nastaliq script
    so Edge TTS's ur-PK-AsadNeural pronounces words with 100% native Pakistani pronunciation."""

    def test_transliterate_salutation_and_verbs(self) -> None:
        input_text = "Jee Sir Abdullah, ab se main Urdu mein baat karunga. Boliye, aap ke liye kya madad kar sakta hoon?"
        res = convert_roman_urdu_to_script(input_text)
        assert "جی سر عبداللہ" in res
        assert "اب سے" in res
        assert "میں" in res
        assert "اردو" in res
        assert "بات کروں گا" in res
        assert "مدد" in res
        assert "کر سکتا ہوں" in res

    def test_transliterate_service_greeting(self) -> None:
        input_text = "Jee Sir Abdullah, main hamesha aap ki khidmat ke liye tayyar hoon. Bataiye, kya karna hai?"
        res = convert_roman_urdu_to_script(input_text)
        assert "جی سر عبداللہ" in res
        assert "ہمیشہ" in res
        assert "خدمت" in res
        assert "تیار ہوں" in res
        assert "بتائیے" in res

    def test_english_text_untouched(self) -> None:
        input_text = "Positive sir, Google Chrome is ready."
        res = convert_roman_urdu_to_script(input_text)
        assert "Positive" in res
        assert "Google Chrome" in res

    def test_humanize_urdu_speech_pauses(self) -> None:
        input_text = "جی سر عبداللہ، میں بالکل ٹھیک ہوں۔ سب کچھ بہترین چل رہا ہے۔ بتائیے سر، کیا خدمت کروں؟"
        res = humanize_urdu_speech(input_text)
        assert "..." in res
        assert "جی سر عبداللہ" in res
        assert "ٹھیک ہوں" in res


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
    """Verifies that check_fast_path provides 0ms responses with authentic Urdu script."""

    def test_language_mode_switching(self) -> None:
        res_ur = check_fast_path("speak in urdu")
        assert res_ur is not None
        assert "جی سر عبداللہ" in res_ur
        assert "اردو" in res_ur

        res_en = check_fast_path("speak in english")
        assert res_en is not None
        assert "Positive sir" in res_en
        assert "English" in res_en

    def test_urdu_greetings(self) -> None:
        res1 = check_fast_path("kya haal hai")
        assert res1 is not None
        assert "جی سر عبداللہ" in res1
        assert "ٹھیک" in res1

        res2 = check_fast_path("kaise ho jarvis")
        assert res2 is not None
        assert "جی سر عبداللہ" in res2

        res3 = check_fast_path("tum kaun ho")
        assert res3 is not None
        assert "جاروس" in res3

    def test_urdu_time_and_date(self) -> None:
        res_time = check_fast_path("kya time hai")
        assert res_time is not None
        assert "جی سر عبداللہ" in res_time
        assert "اس وقت" in res_time

        res_waqt = check_fast_path("waqt batao")
        assert res_waqt is not None
        assert "جی سر عبداللہ" in res_waqt
        assert "اس وقت" in res_waqt

        res_date = check_fast_path("aaj kya tareekh hai")
        assert res_date is not None
        assert "جی سر عبداللہ" in res_date
        assert "آج" in res_date

    @patch("actions.system.volume_up")
    def test_urdu_volume_up(self, mock_vol_up) -> None:
        res = check_fast_path("awaz barhao")
        assert res is not None
        assert "والیم بڑھا دیا ہے" in res
        mock_vol_up.assert_called_once()

    @patch("actions.system.volume_down")
    def test_urdu_volume_down(self, mock_vol_down) -> None:
        res = check_fast_path("awaz kam karo")
        assert res is not None
        assert "والیم کم کر دیا ہے" in res
        mock_vol_down.assert_called_once()

    @patch("actions.system.volume_mute")
    def test_urdu_volume_mute(self, mock_mute) -> None:
        res = check_fast_path("awaz band karo")
        assert res is not None
        assert "آواز بند کر دی ہے" in res
        mock_mute.assert_called_once()

    @patch("actions.system._empty_recycle_bin")
    def test_urdu_recycle_bin(self, mock_empty) -> None:
        res = check_fast_path("recycle bin saaf karo")
        assert res is not None
        assert "ری سائیکل بن صاف" in res
        mock_empty.assert_called_once()

    def test_english_commands_unaffected(self) -> None:
        """Confirms English fast paths continue to return 'Positive sir,'."""
        res_hello = check_fast_path("hello jarvis")
        assert res_hello == "At your service, Sir Abdullah. How may I assist you?"

        res_wake = check_fast_path("wake up")
        assert res_wake == "Sir Abdullah, I am awake and all systems are fully operational."

        res_who = check_fast_path("who are you")
        assert res_who == "I am JARVIS, your personal desktop automation AI assistant."
