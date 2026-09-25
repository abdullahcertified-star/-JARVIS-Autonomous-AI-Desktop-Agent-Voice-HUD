"""vision action: multimodal screen perception, visual QA, and OCR via Google Gemini VLM."""

from __future__ import annotations

import io
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

import config
from actions.screenshot import capture_image
from dispatcher import register
from utils.helpers import fail, ok


def capture_screen_jpeg(region: list[int] | None = None, max_dim: int = 1920) -> bytes:
    """Captures a screenshot, scales it for fast transmission, and returns JPEG bytes."""
    img = capture_image(region)
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _get_genai_client() -> genai.Client:
    api_key = config.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=api_key)


def _analyze_screen(data: dict[str, Any]) -> dict[str, Any]:
    """Inspects the desktop screen with a custom visual QA prompt."""
    prompt = (
        data.get("prompt")
        or data.get("query")
        or "Describe what is currently visible on the screen concisely in 1 to 2 sentences."
    )
    region = data.get("region")

    try:
        jpeg_bytes = capture_screen_jpeg(region)
        client = _get_genai_client()
        image_part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")

        model = getattr(config, "JARVIS_GEMINI_MODEL", "gemini-2.5-flash")
        response = client.models.generate_content(
            model=model,
            contents=[
                image_part,
                (
                    "You are JARVIS multimodal vision system. Analyze this screenshot of the user's desktop display. "
                    f"User request: {prompt}\n\n"
                    "DIRECTIVE: Give a razor-sharp, natural response in 1-2 concise sentences. "
                    "Do not use markdown formatting, asterisks, bullet points, or filler words. Speak naturally."
                ),
            ],
        )
        reply = (response.text or "").strip()
        return ok(reply, analysis=reply)
    except Exception as exc:
        return fail(f"Screen analysis failed: {exc}")


def _explain_error(data: dict[str, Any]) -> dict[str, Any]:
    """Specifically inspects the screen for active error dialogs, exceptions, or warnings."""
    context = data.get("context", "")
    region = data.get("region")

    try:
        jpeg_bytes = capture_screen_jpeg(region)
        client = _get_genai_client()
        image_part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")

        model = getattr(config, "JARVIS_GEMINI_MODEL", "gemini-2.5-flash")
        response = client.models.generate_content(
            model=model,
            contents=[
                image_part,
                (
                    "You are JARVIS screen perception system. Inspect this screenshot specifically for any active error dialogs, "
                    "terminal tracebacks, red alert banners, exception messages, or failure notifications. "
                    f"Additional context: {context}\n\n"
                    "DIRECTIVE: State what the error is and how to fix it in 1 to 2 concise sentences. "
                    "If no error is visible on the screen, state that no active error is currently displayed. "
                    "Do not use asterisks or bullet points. Speak directly to Sir Abdullah."
                ),
            ],
        )
        reply = (response.text or "").strip()
        return ok(reply, explanation=reply)
    except Exception as exc:
        return fail(f"Error explanation failed: {exc}")


def _read_text(data: dict[str, Any]) -> dict[str, Any]:
    """Extracts all visible text on the screen using Gemini VLM."""
    region = data.get("region")

    try:
        jpeg_bytes = capture_screen_jpeg(region)
        client = _get_genai_client()
        image_part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")

        model = getattr(config, "JARVIS_GEMINI_MODEL", "gemini-2.5-flash")
        response = client.models.generate_content(
            model=model,
            contents=[
                image_part,
                (
                    "Transcribe all readable text visible on this screen verbatim. "
                    "Keep the extracted text clean and organized."
                ),
            ],
        )
        reply = (response.text or "").strip()
        return ok("Screen text transcribed", text=reply)
    except Exception as exc:
        return fail(f"Screen text extraction failed: {exc}")


_OPERATIONS = {
    "analyze_screen": _analyze_screen,
    "describe_screen": _analyze_screen,
    "explain_error": _explain_error,
    "read_text": _read_text,
}


@register("vision")
def vision_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown vision operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
