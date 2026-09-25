"""Command action: Knowledge base query, safe execution, and natural-language intent mapping.

Exposes operations:
- execute: translates natural language or runs a validated command through the safety engine.
- match: returns intent, generated command, parameters, and risk classification without running.
- search: searches the 492 commands from the Windows Command Master Reference.
- info: retrieves detailed metadata for a command by name or ID.
"""

from __future__ import annotations

from typing import Any

from commands.database import get_command_db
from commands.executor import CommandExecutor
from commands.intent_matcher import IntentMatcher
from commands.interpreter import ResultInterpreter
from commands.safety import SafetyEngine
from dispatcher import register
from utils.helpers import fail, ok


_matcher = IntentMatcher()
_db = get_command_db()


def _execute(data: dict[str, Any]) -> dict[str, Any]:
    """Executes a natural language request or a direct command safely."""
    request_text = data.get("request") or data.get("text") or data.get("query")
    raw_command = data.get("command")
    confirmed = bool(data.get("confirmed", False))
    shell = data.get("shell", "cmd")

    if request_text:
        # Use the intent matcher for natural language translation + safety + execution
        result = _matcher.execute_request(str(request_text), confirmed=confirmed)
        if result.get("requires_confirmation") and not confirmed:
            try:
                from voice.ui import get_active_window
                win = get_active_window()
                if win:
                    approved = win.wait_for_confirmation(
                        command=result.get("command", str(request_text)),
                        shell=result.get("shell", "cmd"),
                        risk_level=result.get("risk_level", "HIGH"),
                        reason=result.get("message", "High privilege command requires explicit confirmation."),
                        timeout_seconds=20,
                    )
                    if approved:
                        return _execute({**data, "confirmed": True})
                    return fail("Command execution was cancelled by user.", **result)
            except Exception:
                pass

        msg = result.get("message", "OK")
        extra = {k: v for k, v in result.items() if k != "message"}
        return ok(msg, **extra) if result.get("success") else fail(msg, **extra)

    if raw_command:
        # Direct command execution with safety enforcement
        cmd_str = str(raw_command).strip()
        exec_result = CommandExecutor.execute(
            command=cmd_str,
            shell=shell,
            cwd=data.get("cwd"),
            timeout=data.get("timeout"),
            confirmed=confirmed,
        )
        if exec_result.get("requires_confirmation") and not confirmed:
            try:
                from voice.ui import get_active_window
                win = get_active_window()
                if win:
                    approved = win.wait_for_confirmation(
                        command=cmd_str,
                        shell=shell,
                        risk_level=exec_result.get("risk_level", "HIGH"),
                        reason=exec_result.get("message", "High privilege command requires explicit confirmation."),
                        timeout_seconds=20,
                    )
                    if approved:
                        return _execute({**data, "confirmed": True})
                    return fail("Command execution was cancelled by user.", **exec_result)
            except Exception:
                pass

        spoken = ResultInterpreter.interpret(cmd_str, exec_result)
        exec_result["response"] = spoken
        extra = {k: v for k, v in exec_result.items() if k != "message"}
        return ok(spoken, **extra) if exec_result.get("success") else fail(spoken, **extra)

    return fail("command.execute requires either 'request' (natural language) or 'command' (CLI string)")


def _match(data: dict[str, Any]) -> dict[str, Any]:
    """Matches a natural-language request and returns intent and safety metadata without executing."""
    request_text = data.get("request") or data.get("text") or data.get("query")
    if not request_text:
        return fail("command.match requires 'request' (string)")

    intent = _matcher.match(str(request_text))
    return ok(
        f"Matched intent: {intent.intent_name}",
        intent=intent.intent_name,
        command=intent.command,
        shell=intent.shell,
        risk_level=intent.risk_level.value,
        requires_admin=intent.requires_admin,
        destructive=intent.destructive,
        requires_confirmation=intent.requires_confirmation,
        confirmation_prompt=intent.confirmation_prompt,
        parameters=intent.parameters,
        description=intent.description,
    )


def _search(data: dict[str, Any]) -> dict[str, Any]:
    """Searches the command database."""
    query = data.get("query") or data.get("text") or ""
    limit = int(data.get("limit", 5))
    results = _db.search(str(query), limit=limit)
    return ok(f"Found {len(results)} command match(es)", matches=results, count=len(results))


def _info(data: dict[str, Any]) -> dict[str, Any]:
    """Retrieves full information for a command by name or ID."""
    name = data.get("name") or data.get("command")
    cmd_id = data.get("id")

    if cmd_id is not None:
        try:
            cmd = _db.get_by_id(int(cmd_id))
            if cmd:
                return ok(f"Retrieved command #{cmd_id}", command=cmd)
        except (ValueError, TypeError):
            pass

    if name:
        cmd = _db.get_by_name(str(name))
        if cmd:
            return ok(f"Retrieved command '{name}'", command=cmd)

    return fail(f"Command not found: id={cmd_id}, name={name}")


_OPERATIONS = {
    "execute": _execute,
    "match": _match,
    "search": _search,
    "info": _info,
}


@register("command")
def command_action(data: dict[str, Any]) -> dict[str, Any]:
    operation = data.get("operation")
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return fail(f"Unknown command operation '{operation}'. Options: {', '.join(_OPERATIONS)}")
    return handler(data)
