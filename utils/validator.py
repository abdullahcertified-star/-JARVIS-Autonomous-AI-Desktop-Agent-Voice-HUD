"""Request validation for the /execute endpoint.

Each entry in ACTION_SCHEMAS lists the top-level fields a request for that
action must contain. This is intentionally shallow -- operation-specific
requirements (e.g. "text" only when keyboard operation == "type") are
validated inside the relevant action handler, which is better placed to
produce a precise error message.
"""

from __future__ import annotations

ACTION_SCHEMAS: dict[str, list[str]] = {
    # open_app deliberately has no required field here: actions.apps.open_app
    # accepts "target", "app", or "app_name" interchangeably and produces its
    # own precise "No application specified" error, so enforcing one specific
    # field name here would wrongly reject callers using a valid synonym.
    "open_app": [],
    "refresh_apps": [],
    "open_url": ["url"],
    "search_google": ["query"],
    "search_youtube": ["query"],
    "get_news": [],
    "keyboard": ["operation"],
    "mouse": ["operation"],
    "clipboard": ["operation"],
    "explorer": ["operation"],
    "system": ["operation"],
    "media": ["operation"],
    "ocr": ["operation"],
    "screenshot": ["operation"],
    "command": ["operation"],
    "vision": ["operation"],
    "macro": ["operation"],
}



def validate_request(data: object) -> tuple[bool, str | None]:
    """Validates the raw JSON body of an /execute request.

    Returns (True, None) if valid, otherwise (False, error_message).
    """
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object"

    action = data.get("action")
    if not action or not isinstance(action, str):
        return False, "Missing or invalid 'action' field"

    if action not in ACTION_SCHEMAS:
        known = ", ".join(sorted(ACTION_SCHEMAS))
        return False, f"Unknown action '{action}'. Known actions: {known}"

    missing = [field for field in ACTION_SCHEMAS[action] if not data.get(field)]
    if missing:
        return False, f"Missing required field(s) for '{action}': {', '.join(missing)}"

    return True, None
