"""ocr action: extract text from the screen via Tesseract OCR.

Tesseract itself is a native binary, not a pip package -- if it isn't
installed/on PATH, every operation here fails cleanly with instructions
instead of raising.
"""

from __future__ import annotations

import shutil
from typing import Any

from actions.screenshot import capture_image
from dispatcher import register
from utils.helpers import fail, ok

_TESSERACT_HINT = (
    "Tesseract OCR is not installed or not on PATH. Install it from "
    "https://github.com/UB-Mannheim/tesseract/wiki and ensure 'tesseract' "
    "is reachable from the command line."
)


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _read(data: dict[str, Any]) -> dict[str, Any]:
    if not _tesseract_available():
        return fail(_TESSERACT_HINT)

    import pytesseract  # imported lazily so the module loads even without pytesseract installed

    region = data.get("region")
    if region is not None and (not isinstance(region, list) or len(region) != 4):
        return fail("ocr 'region' must be [x, y, width, height]")

    image = capture_image(region)
    text = pytesseract.image_to_string(image).strip()

    return ok("OCR complete", text=text)


_OPERATIONS = {
    "read_screen": _read,
    "read_region": _read,
}


@register("ocr")
def ocr_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown ocr operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    if operation == "read_region" and not data.get("region"):
        return fail("ocr.read_region requires 'region': [x, y, width, height]")
    return handler(data)
