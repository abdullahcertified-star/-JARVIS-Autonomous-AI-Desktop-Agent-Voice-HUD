"""macro action: multi-step workflow automation and custom macro orchestrator."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import config
from dispatcher import register
from utils.helpers import fail, ok

logger = logging.getLogger(__name__)

DEFAULT_WORKFLOWS: dict[str, dict[str, Any]] = {
    "dev_workspace": {
        "description": "Initialize development workspace with VS Code, Terminal, GitHub, and 30% volume.",
        "steps": [
            {"action": "open_app", "target": "Code"},
            {"action": "open_app", "target": "cmd"},
            {"action": "open_url", "url": "https://github.com"},
            {"action": "system", "operation": "set_volume", "level": 30},
        ],
    },
    "goodnight_routine": {
        "description": "Pause media, set volume to 0%, minimize all windows, and dim brightness.",
        "steps": [
            {"action": "media", "operation": "play_pause"},
            {"action": "system", "operation": "set_volume", "level": 0},
            {"action": "system", "operation": "minimize_all"},
            {"action": "system", "operation": "set_brightness", "level": 10},
        ],
    },
    "meeting_mode": {
        "description": "Pause background audio, adjust conversational volume, and minimize window clutter.",
        "steps": [
            {"action": "media", "operation": "play_pause"},
            {"action": "system", "operation": "set_volume", "level": 40},
            {"action": "system", "operation": "minimize_all"},
        ],
    },
    "gaming_mode": {
        "description": "Boost master volume and maximize screen brightness for gaming.",
        "steps": [
            {"action": "system", "operation": "set_volume", "level": 70},
            {"action": "system", "operation": "set_brightness", "level": 100},
        ],
    },
    "morning_briefing": {
        "description": "Set comfortable volume, fetch tech news, and check system status.",
        "steps": [
            {"action": "system", "operation": "set_volume", "level": 50},
            {"action": "get_news", "category": "technology"},
            {"action": "system", "operation": "status"},
        ],
    },
}


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def load_workflows() -> dict[str, dict[str, Any]]:
    """Loads workflows from storage, merged with built-in defaults."""
    workflows = dict(DEFAULT_WORKFLOWS)
    path = getattr(config, "WORKFLOWS_JSON_PATH", None)
    if path and path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    workflows.update(saved)
        except Exception as exc:
            logger.warning("Could not read workflows file %s: %s", path, exc)
    return workflows


def save_workflows(workflows: dict[str, dict[str, Any]]) -> None:
    """Persists workflows to storage."""
    path = getattr(config, "WORKFLOWS_JSON_PATH", None)
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(workflows, f, indent=2)
    except Exception as exc:
        logger.warning("Could not save workflows to %s: %s", path, exc)


def run_workflow_by_name(name: str) -> dict[str, Any]:
    """Executes a workflow by name step-by-step."""
    from dispatcher import dispatch

    norm_name = _normalize_name(name)
    workflows = load_workflows()

    workflow = workflows.get(norm_name)
    if not workflow:
        # Match without underscores or partial match
        for k, v in workflows.items():
            if k.replace("_", "") == norm_name.replace("_", "") or norm_name in k:
                workflow = v
                norm_name = k
                break

    if not workflow:
        available = ", ".join(workflows.keys())
        return fail(f"Workflow '{name}' not found. Available workflows: {available}")

    steps = workflow.get("steps", [])
    if not steps:
        return ok(f"Workflow '{norm_name}' has no configured steps.", steps_run=0)

    results = []
    success_count = 0

    for idx, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            continue

        step_payload = dict(step)
        delay = float(step_payload.pop("delay", 0.0))

        try:
            res = dispatch(step_payload)
            is_ok = bool(res.get("success", False))
            if is_ok:
                success_count += 1
            results.append({
                "step": idx,
                "action": step_payload.get("action", "unknown"),
                "success": is_ok,
                "message": res.get("message", ""),
            })
        except Exception as exc:
            results.append({
                "step": idx,
                "action": step_payload.get("action", "unknown"),
                "success": False,
                "message": str(exc),
            })

        if delay > 0:
            time.sleep(delay)

    total = len(steps)
    summary = f"Positive sir, workflow '{norm_name}' completed: {success_count}/{total} steps executed successfully."
    return ok(summary, workflow=norm_name, steps_total=total, steps_succeeded=success_count, details=results)


def _list_workflows(_data: dict[str, Any]) -> dict[str, Any]:
    """Returns a list of all registered workflows."""
    workflows = load_workflows()
    summary_list = []
    for k, v in workflows.items():
        desc = v.get("description", "Custom workflow")
        count = len(v.get("steps", []))
        summary_list.append(f"• {k} ({count} steps): {desc}")

    message = f"Found {len(workflows)} configured workflows:\n" + "\n".join(summary_list)
    return ok(message, workflows=workflows)


def _save_workflow(data: dict[str, Any]) -> dict[str, Any]:
    """Creates or updates a custom workflow."""
    name = data.get("name")
    if not name or not isinstance(name, str):
        return fail("A workflow 'name' string is required.")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        return fail("A non-empty 'steps' list of action payloads is required.")

    norm_name = _normalize_name(name)
    description = str(data.get("description") or f"Custom workflow: {norm_name}")

    workflows = load_workflows()
    workflows[norm_name] = {
        "description": description,
        "steps": steps,
    }
    save_workflows(workflows)
    return ok(f"Workflow '{norm_name}' saved with {len(steps)} steps.", name=norm_name, steps_count=len(steps))


def _delete_workflow(data: dict[str, Any]) -> dict[str, Any]:
    """Deletes a custom workflow."""
    name = data.get("name")
    if not name or not isinstance(name, str):
        return fail("A workflow 'name' string is required.")

    norm_name = _normalize_name(name)
    workflows = load_workflows()
    if norm_name not in workflows:
        return fail(f"Workflow '{norm_name}' does not exist.")

    del workflows[norm_name]
    save_workflows(workflows)
    return ok(f"Workflow '{norm_name}' has been deleted.", name=norm_name)


def _run_workflow(data: dict[str, Any]) -> dict[str, Any]:
    name = data.get("name") or data.get("workflow") or data.get("target")
    if not name:
        return fail("Please specify the workflow 'name' to execute.")
    return run_workflow_by_name(str(name))


_OPERATIONS = {
    "run": _run_workflow,
    "execute": _run_workflow,
    "list": _list_workflows,
    "save": _save_workflow,
    "create": _save_workflow,
    "delete": _delete_workflow,
    "remove": _delete_workflow,
}


@register("macro")
def macro_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown macro operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
