"""Tests for actions/vision.py and vision integration in agent.py."""

from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from dispatcher import dispatch
from actions import vision
from actions.vision import capture_screen_jpeg
import agent



def test_capture_screen_jpeg_small():
    mock_img = Image.new("RGB", (200, 100), color="red")
    with patch("actions.vision.capture_image", return_value=mock_img):
        jpeg_bytes = capture_screen_jpeg()
        assert isinstance(jpeg_bytes, bytes)
        assert jpeg_bytes.startswith(b"\xff\xd8\xff")


def test_capture_screen_jpeg_downscale():
    mock_img = Image.new("RGB", (3840, 2160), color="blue")
    with patch("actions.vision.capture_image", return_value=mock_img):
        jpeg_bytes = capture_screen_jpeg(max_dim=1920)
        assert isinstance(jpeg_bytes, bytes)
        assert len(jpeg_bytes) > 0


def test_analyze_screen_dispatch():
    mock_response = MagicMock()
    mock_response.text = "You are currently viewing a Python source file in VS Code."

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    mock_img = Image.new("RGB", (100, 100), color="white")
    with patch("actions.vision.capture_image", return_value=mock_img), \
         patch("actions.vision._get_genai_client", return_value=mock_client):
        res = dispatch({
            "action": "vision",
            "operation": "describe_screen",
            "prompt": "What is on my screen?",
        })
        assert res["success"] is True
        assert "VS Code" in res["message"]
        assert res["analysis"] == "You are currently viewing a Python source file in VS Code."


def test_explain_error_dispatch():
    mock_response = MagicMock()
    mock_response.text = "The screen shows a SyntaxError on line 42 due to a missing closing parenthesis."

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    mock_img = Image.new("RGB", (100, 100), color="black")
    with patch("actions.vision.capture_image", return_value=mock_img), \
         patch("actions.vision._get_genai_client", return_value=mock_client):
        res = dispatch({
            "action": "vision",
            "operation": "explain_error",
            "context": "Syntax error popup",
        })
        assert res["success"] is True
        assert "SyntaxError" in res["explanation"]


def test_read_text_dispatch():
    mock_response = MagicMock()
    mock_response.text = "System Online\nBattery: 100%\nWiFi: Connected"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    mock_img = Image.new("RGB", (100, 100), color="black")
    with patch("actions.vision.capture_image", return_value=mock_img), \
         patch("actions.vision._get_genai_client", return_value=mock_client):
        res = dispatch({
            "action": "vision",
            "operation": "read_text",
        })
        assert res["success"] is True
        assert "System Online" in res["text"]


def test_vision_invalid_operation():
    res = dispatch({
        "action": "vision",
        "operation": "non_existent_op",
    })
    assert res["success"] is False
    assert "Unknown vision operation" in res["message"]


def test_agent_vision_tools():
    with patch("agent.dispatch") as mock_dispatch:
        mock_dispatch.return_value = {"success": True, "message": "Desktop looks clear."}
        desc = agent.describe_screen("any open windows?")
        assert "Desktop looks clear." in desc

        mock_dispatch.return_value = {"success": True, "message": "No errors detected."}
        err = agent.explain_screen_error()
        assert "No errors detected." in err


def test_read_screen_text_fallback():
    # If OCR fails (e.g. no tesseract), falls back to vision
    with patch("agent.dispatch") as mock_dispatch:
        mock_dispatch.side_effect = [
            {"success": False, "message": "tesseract is not installed"},
            {"success": True, "message": "Screen text transcribed", "text": "Extracted with Gemini VLM"},
        ]
        res = agent.read_screen_text()
        assert "Extracted with Gemini VLM" in res


def test_check_fast_path_screen_perception():
    with patch("agent.describe_screen", return_value="Sir, you have your IDE open.") as mock_desc, \
         patch("agent.explain_screen_error", return_value="Sir, no active errors found.") as mock_err:
        res1 = agent.check_fast_path("Jarvis, what is on my screen?")
        assert res1 == "Sir, you have your IDE open."
        mock_desc.assert_called_once()

        res2 = agent.check_fast_path("explain this error on screen")
        assert res2 == "Sir, no active errors found."
        mock_err.assert_called_once()
