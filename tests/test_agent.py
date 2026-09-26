"""Tests for the agent module (agent.py) and the /chat endpoint in app.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

import agent
from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config.update(TESTING=True)
    return flask_app.test_client()


def test_format_result_handles_various_payloads() -> None:
    # Basic message
    res1 = {"success": True, "message": "Volume increased"}
    assert "Volume increased" in agent._format_result(res1)

    # Detailed status with numbers
    res2 = {
        "success": True,
        "message": "System status",
        "cpu_percent": 12.5,
        "memory_percent": 45.0,
        "muted": False,
    }
    formatted2 = agent._format_result(res2)
    assert "System status" in formatted2
    assert "cpu_percent: 12.5" in formatted2
    assert "memory_percent: 45.0" in formatted2

    # Directory entries
    res3 = {
        "success": True,
        "message": "Listed items",
        "entries": [{"name": "file1.txt"}, {"name": "file2.txt"}],
    }
    formatted3 = agent._format_result(res3)
    assert "file1.txt" in formatted3
    assert "file2.txt" in formatted3

    # Command output
    res4 = {
        "success": True,
        "message": "Command exited with code 0",
        "stdout": "Hello World\n",
        "exit_code": 0,
    }
    formatted4 = agent._format_result(res4)
    assert "Hello World" in formatted4
    assert "exit_code: 0" in formatted4


def test_tools_delegate_to_dispatch() -> None:
    with patch("agent.dispatch") as mock_dispatch:
        mock_dispatch.return_value = {"success": True, "message": "OK"}

        agent.open_app("chrome")
        mock_dispatch.assert_called_with({"action": "open_app", "target": "chrome"})

        agent.search_google("python news", browser="edge")
        mock_dispatch.assert_called_with({"action": "search_google", "query": "python news", "browser": "edge"})

        agent.search_youtube("lofi hip hop")
        mock_dispatch.assert_called_with({"action": "search_youtube", "query": "lofi hip hop"})

        agent.set_volume(50)
        mock_dispatch.assert_called_with({"action": "system", "operation": "set_volume", "level": 50})

        agent.adjust_volume("mute")
        mock_dispatch.assert_called_with({"action": "system", "operation": "mute"})

        agent.media_control("play_pause")
        mock_dispatch.assert_called_with({"action": "media", "operation": "play_pause"})

        agent.get_system_status()
        mock_dispatch.assert_called_with({"action": "system", "operation": "status"})

        agent.system_power("lock")
        mock_dispatch.assert_called_with({"action": "system", "operation": "lock"})

        agent.run_command("dir", cwd="C:\\")
        mock_dispatch.assert_called_with({"action": "system", "operation": "run_command", "command": "dir", "cwd": "C:\\"})

        agent.manage_files("read", "C:\\test.txt")
        mock_dispatch.assert_called_with({
            "action": "explorer",
            "operation": "read",
            "path": "C:\\test.txt",
            "content": "",
            "append": False,
            "is_folder": False,
        })


def test_chat_endpoint_requires_message(client) -> None:
    response = client.post("/chat", json={})
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert "No message provided" in body["message"]


def test_chat_endpoint_delegates_to_agent(client) -> None:
    with patch("agent.get_agent") as mock_get_agent:
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "Positive, sir. Action completed."
        mock_get_agent.return_value = mock_agent

        response = client.post("/chat", json={"message": "Set volume to 50"})
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert body["reply"] == "Positive, sir. Action completed."
        mock_agent.chat.assert_called_once_with("Set volume to 50")


def test_chat_reset_endpoint(client) -> None:
    with patch("agent.get_agent") as mock_get_agent:
        mock_agent = MagicMock()
        mock_get_agent.return_value = mock_agent

        response = client.post("/chat/reset")
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert "reset" in body["message"].lower()
        mock_agent.reset_chat.assert_called_once()


def test_clean_markdown_for_speech() -> None:
    from voice.pipeline import clean_markdown_for_speech

    raw = "Sir Abdullah, **VMnet1:** `192.168.160.1` and - **VMnet8:** `192.168.75.1`"
    cleaned = clean_markdown_for_speech(raw)
    assert "*" not in cleaned
    assert "`" not in cleaned
    assert "VMnet1:" in cleaned
    assert "192.168.160.1" in cleaned
    assert "VMnet8:" in cleaned


def test_split_sentences_cleans_and_streams() -> None:
    from voice.pipeline import split_sentences

    raw = "Positive, sir. **All systems** are `online`. Is there anything else?"
    sentences = split_sentences(raw)
    assert len(sentences) >= 2
    for s in sentences:
        assert "*" not in s
        assert "`" not in s


def test_normalize_transcription() -> None:
    from voice.pipeline import normalize_transcription

    assert normalize_transcription("Hey, Jairuis") == "Hey, Jarvis"
    assert normalize_transcription("Hey jairus open chrome") == "Hey Jarvis open chrome"
    assert normalize_transcription("Hey service what is my IP") == "Hey Jarvis what is my IP"
    assert normalize_transcription("Jarvus status report") == "Jarvis status report"
    assert normalize_transcription("open the drive app") == "open drive F"
    assert normalize_transcription("open drive app") == "open drive F"
    assert normalize_transcription("open F drive") == "open drive F"
    assert normalize_transcription("open local disk D") == "open drive D"


def test_fast_path_drive_queries() -> None:
    from agent import check_fast_path

    # Drive F should open Drive F (or report opened if F: exists)
    res_f = check_fast_path("open drive F")
    assert res_f is not None
    assert "Drive F:" in res_f

    # "open the drive app" mishearing should resolve to Drive F or File Explorer
    res_mishear = check_fast_path("open the drive app")
    assert res_mishear is not None
    assert "Drive F:" in res_mishear or "File Explorer" in res_mishear

    # "open file explorer" should open Explorer
    res_explorer = check_fast_path("open file explorer")
    assert res_explorer is not None
    assert "File Explorer" in res_explorer


def test_format_speech_ssml_humanized() -> None:
    from voice.pipeline import format_speech_ssml

    text = "Positive sir, I have opened Drive F for you. Let me know what to do next."
    ssml = format_speech_ssml(text, comma_ms=700, period_ms=1000)
    assert '<break time="700ms"/>' in ssml
    assert '<break time="1000ms"/>' in ssml


def test_new_tools_delegate_to_dispatch() -> None:
    with patch("agent.dispatch") as mock_dispatch:
        mock_dispatch.return_value = {"success": True, "message": "OK"}

        agent.close_app("notepad")
        mock_dispatch.assert_called_with({"action": "system", "operation": "close_app", "target": "notepad"})

        agent.list_running_apps(limit=5)
        mock_dispatch.assert_called_with({"action": "system", "operation": "list_processes", "limit": 5})

        agent.empty_recycle_bin()
        mock_dispatch.assert_called_with({"action": "system", "operation": "empty_recycle_bin"})

        agent.set_screen_brightness(80)
        mock_dispatch.assert_called_with({"action": "system", "operation": "screen_brightness", "level": 80})

        agent.get_wifi_status()
        mock_dispatch.assert_called_with({"action": "system", "operation": "wifi_info"})

        agent.network_ping("1.1.1.1")
        mock_dispatch.assert_called_with({"action": "system", "operation": "ping", "host": "1.1.1.1"})

        agent.search_files("report.pdf", root_folder="C:\\test")
        mock_dispatch.assert_called_with({"action": "explorer", "operation": "search", "query": "report.pdf", "root_folder": "C:\\test"})

        agent.read_screen_text(region=[0, 0, 100, 100])
        mock_dispatch.assert_called_with({"action": "ocr", "operation": "read_region", "region": [0, 0, 100, 100]})


def test_new_fast_paths() -> None:
    from agent import check_fast_path

    # Empty recycle bin
    with patch("actions.system._empty_recycle_bin") as mock_empty:
        mock_empty.return_value = {"success": True, "message": "Empty"}
        res = check_fast_path("empty recycle bin")
        assert res is not None
        assert "Recycle Bin" in res

    # Desktop window management
    res_min = check_fast_path("minimize all windows")
    assert res_min is not None
    assert "minimized" in res_min.lower()

    res_res = check_fast_path("restore windows")
    assert res_res is not None
    assert "restored" in res_res.lower()

    # Wi-Fi check
    with patch("actions.system._wifi_info") as mock_wifi:
        mock_wifi.return_value = {"success": True, "ssid": "HomeNetwork", "signal": "95%", "state": "connected"}
        res_wifi = check_fast_path("check wifi status")
        assert res_wifi is not None
        assert "HomeNetwork" in res_wifi

    # Weather check
    with patch("agent.get_weather") as mock_weather:
        mock_weather.return_value = "Sunny: +25°C, humidity 40%"
        res_weather = check_fast_path("what is the weather today")
        assert res_weather is not None
        assert "+25°C" in res_weather


def test_brevity_enforced_in_chat() -> None:
    from agent import JarvisAgent

    with patch("agent.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_client.chats.create.return_value = mock_chat
        mock_client_cls.return_value = mock_client

        jarvis = JarvisAgent(api_key="fake-key", model="gemini-2.5-flash")

        # Mock a long, verbose 5-sentence response with markdown asterisks
        verbose_reply = (
            "**Cicada 3301** is an infamous cryptographic puzzle group that emerged in 2012. "
            "Their puzzles focused heavily on steganography, data security, and cryptography. "
            "Many believed it was a recruitment tool for intelligence agencies like the CIA. "
            "A third puzzle was posted in 2014 and remains partially unsolved to this day. "
            "They posted their final verified message in April 2017."
        )
        mock_response = MagicMock()
        mock_response.text = verbose_reply
        mock_chat.send_message.return_value = mock_response

        # Normal question: should be condensed to at most 2 sentences with markdown stripped!
        result = jarvis.chat("What is Cicada 3301?")
        assert "**" not in result
        sentences = [s for s in result.split(".") if s.strip()]
        assert len(sentences) <= 2
        assert "Cicada 3301 is an infamous cryptographic puzzle group" in result


def test_wake_up_and_greetings_fast_path() -> None:
    from agent import check_fast_path

    res_wake = check_fast_path("wake up")
    assert res_wake is not None
    assert "awake" in res_wake.lower()

    res_wake2 = check_fast_path("wake up jarvis")
    assert res_wake2 is not None
    assert "awake" in res_wake2.lower()

    res_hello = check_fast_path("hello jarvis")
    assert res_hello is not None
    assert "service" in res_hello.lower()

    res_who = check_fast_path("who are you")
    assert res_who is not None
    assert "jarvis" in res_who.lower()


def test_additional_useful_tools() -> None:
    # 1. Math calculation
    res_math = agent.calculate("25 * 4 + 10")
    assert "110" in res_math

    res_sqrt = agent.calculate("sqrt(144)")
    assert "12" in res_sqrt

    # 2. Detailed system info
    res_info = agent.get_detailed_system_info()
    assert "RAM:" in res_info
    assert "Drives:" in res_info

    # 3. Quick note
    res_save = agent.quick_note("save", "Test note for jarvis")
    assert "saved" in res_save.lower()

    res_read = agent.quick_note("read")
    assert "Test note for jarvis" in res_read

    # 4. Timer
    res_timer = agent.set_timer(10, label="tea")
    assert "Timer set" in res_timer

    # 5. Open drive
    res_drive = agent.open_drive("C")
    assert "Drive C:" in res_drive


def test_system_utilities_and_settings() -> None:
    # 1. Utilities mapping test
    with patch("subprocess.Popen") as mock_popen:
        res_tm = agent.launch_system_utility("task_manager")
        assert "launched task_manager" in res_tm
        mock_popen.assert_called_once()

    # 2. Windows Settings
    with patch("os.startfile") as mock_startfile:
        res_bt = agent.open_windows_settings("bluetooth")
        assert "Bluetooth Settings" in res_bt
        mock_startfile.assert_called_with("ms-settings:bluetooth")

    # 3. Shutdown scheduling & cancel
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res_shut = agent.schedule_shutdown(15)
        assert "15 minute(s)" in res_shut

        res_cancel = agent.cancel_scheduled_shutdown()
        assert "cancelled" in res_cancel

    # 4. Flush DNS
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res_dns = agent.network_flush_dns()
        assert "successfully flushed" in res_dns

    # 5. Type text into active window
    with patch("keyboard.write") as mock_write, patch("keyboard.send") as mock_send:
        res_type = agent.type_text_into_active_window("Hello", press_enter=True)
        assert "Typed 5 character(s)" in res_type
        mock_write.assert_called_with("Hello")
        mock_send.assert_called_with("enter")

    # 6. Audio devices
    res_audio = agent.list_connected_audio_devices()
    assert "Audio Outputs:" in res_audio

    # 7. Fast path for task manager and flush dns
    with patch("agent.launch_system_utility") as mock_util:
        mock_util.return_value = "Sir Abdullah, launched task_manager."
        res_fp_tm = agent.check_fast_path("open task manager")
        assert res_fp_tm is not None
        assert "task_manager" in res_fp_tm

    with patch("agent.network_flush_dns") as mock_flush:
        mock_flush.return_value = "Flushed."
        res_fp_dns = agent.check_fast_path("flush dns")
        assert res_fp_dns is not None
        assert "Flushed" in res_fp_dns


def test_conversation_session_and_status_prefix() -> None:
    from voice import config as v_config
    from voice.pipeline import enforce_status_prefix

    # 1. Configured conversation timeout must be in the 40-50s range
    assert 40.0 <= v_config.CONVERSATION_TIMEOUT_SEC <= 50.0

    # 2. Positive prefix enforcement
    assert enforce_status_prefix("opened Task Manager.").startswith("Positive sir,")
    assert enforce_status_prefix("Sir Abdullah, your primary IPv4 address is 192.168.1.1.").startswith("Positive sir,")
    assert enforce_status_prefix("Positive sir, volume increased.").startswith("Positive sir,")

    # 3. Negative prefix enforcement
    assert enforce_status_prefix("unable to find that process.").startswith("Negative sir,")
    assert enforce_status_prefix("could not launch notepad.").startswith("Negative sir,")
    assert enforce_status_prefix("Negative sir, access was denied.").startswith("Negative sir,")

    # 4. Greeting & standby preservation
    greeting = "At your service, Sir Abdullah. How may I assist you?"
    assert enforce_status_prefix(greeting) == greeting
    standby = "Standing by, Sir Abdullah."
    assert enforce_status_prefix(standby) == standby


def test_ip_address_fast_path_and_explanations() -> None:
    from agent import check_fast_path

    # 1. Direct value queries return actual IP addresses
    with patch("agent.get_ip_address") as mock_get_ip:
        mock_get_ip.return_value = "Positive sir, your local private IPv4 address is 192.168.1.11."
        res_v4 = check_fast_path("Jarvis tell me what is my ipv4 address")
        assert res_v4 is not None
        assert "192.168.1.11" in res_v4
        mock_get_ip.assert_called_with(ip_type="private")

    with patch("agent.get_ip_address") as mock_get_ip:
        mock_get_ip.return_value = "Positive sir, your public IP address is 58.65.223.234."
        res_pub = check_fast_path("now tell me what is my public IP address")
        assert res_pub is not None
        assert "58.65.223.234" in res_pub
        mock_get_ip.assert_called_with(ip_type="public")

    # 2. Methodology/Process/Command queries return explanation of how/commands used, NOT repeated IP value
    res_how = check_fast_path("tell me how do you find my public IP")
    assert res_how is not None
    assert "api.ipify.org" in res_how or "ifconfig.me" in res_how
    assert "curl" in res_how or "Invoke-RestMethod" in res_how

    res_proc = check_fast_path("I mean what's the process you follow to find my public IP")
    assert res_proc is not None
    assert "ifconfig.me" in res_proc or "api.ipify.org" in res_proc

    res_cmd = check_fast_path("I am saying what commands you use to find the IP address of my system")
    assert res_cmd is not None
    assert "ipconfig" in res_cmd
    assert "curl" in res_cmd or "ifconfig" in res_cmd

    # 3. Bilingual / Roman Urdu query for methodology
    res_ur = check_fast_path("ip kaise pata kiya")
    assert res_ur is not None
    assert "Jee Sir Abdullah" in res_ur
    assert "ipconfig" in res_ur

    # 4. Pure conceptual queries must NOT be intercepted by get_ip_address (fall through to LLM)
    assert check_fast_path("what is ipv4") is None
    assert check_fast_path("what is the difference between public and private IP") is None

    # 5. MAC Address queries MUST return MAC address and NOT fall into IP address lookup!
    with patch("agent.get_mac_address") as mock_mac:
        mock_mac.return_value = "Positive sir, your physical MAC address for Ethernet is FC-AA-14-E0-E9-4D."
        res_mac1 = check_fast_path("Ok Jarvis now tell me what is my Mac address")
        assert res_mac1 is not None
        assert "FC-AA-14-E0-E9-4D" in res_mac1
        assert "public IP" not in res_mac1

        res_mac2 = check_fast_path("I said what is my Mac address")
        assert res_mac2 is not None
        assert "FC-AA-14-E0-E9-4D" in res_mac2
        assert "public IP" not in res_mac2

    # 6. MAC methodology query
    res_mac_cmd = check_fast_path("what commands you use to find the MAC address")
    assert res_mac_cmd is not None
    assert "getmac" in res_mac_cmd

    # 7. Gateway query
    with patch("agent.get_default_gateway") as mock_gw:
        mock_gw.return_value = "Positive sir, your default network gateway is 192.168.1.1."
        res_gw = check_fast_path("what is my default gateway")
        assert res_gw is not None
        assert "192.168.1.1" in res_gw





