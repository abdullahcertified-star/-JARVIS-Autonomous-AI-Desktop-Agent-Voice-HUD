"""Sandboxed and Safe Command Executor for CMD and PowerShell.

Invokes Windows commands with timeout protection, proper shell selection,
working directory control, and tight integration with the SafetyEngine.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import config
from commands.safety import SafetyEngine


class CommandExecutor:
    """Safely executes validated CMD and PowerShell commands."""

    DEFAULT_TIMEOUT: float = float(config.RUN_COMMAND_DEFAULT_TIMEOUT)
    MAX_TIMEOUT: float = float(config.RUN_COMMAND_MAX_TIMEOUT)

    @classmethod
    def execute(
        cls,
        command: str,
        shell: str = "cmd",
        cwd: Optional[str | Path] = None,
        timeout: Optional[float] = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Validates and executes a command in the appropriate shell.

        If the command requires confirmation and `confirmed=False`, execution is blocked
        and a confirmation request dictionary is returned immediately.
        """
        cmd_clean = command.strip()
        shell_clean = shell.lower().strip()
        if shell_clean not in ("cmd", "powershell"):
            shell_clean = "cmd"

        # 1. Safety validation
        allowed, prompt, report = SafetyEngine.validate_execution(
            cmd_clean, shell=shell_clean, confirmed=confirmed
        )

        if not allowed:
            return {
                "success": False,
                "requires_confirmation": report.requires_confirmation,
                "risk_level": report.risk_level.value,
                "requires_admin": report.requires_admin,
                "destructive": report.destructive,
                "command": cmd_clean,
                "shell": shell_clean,
                "message": prompt or "Execution blocked by safety policy.",
            }

        # 2. Timeout normalization
        run_timeout = cls.DEFAULT_TIMEOUT if timeout is None else min(float(timeout), cls.MAX_TIMEOUT)

        # 3. Construct invocation arguments
        if shell_clean == "powershell":
            # Explicit PowerShell invocation with NoProfile and NonInteractive flags
            args = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                cmd_clean,
            ]
        else:
            # Explicit cmd.exe /c invocation
            args = ["cmd.exe", "/c", cmd_clean]

        started = time.perf_counter()

        try:
            result = subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=run_timeout,
                encoding="utf-8",
                errors="replace",
            )
            duration_ms = (time.perf_counter() - started) * 1000

            stdout = result.stdout or ""
            stderr = result.stderr or ""
            is_success = result.returncode == 0

            return {
                "success": is_success,
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": round(duration_ms, 2),
                "risk_level": report.risk_level.value,
                "command": cmd_clean,
                "shell": shell_clean,
                "message": f"Command exited with code {result.returncode}" if is_success else f"Command failed with code {result.returncode}",
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {run_timeout} seconds.",
                "duration_ms": round(run_timeout * 1000, 2),
                "risk_level": report.risk_level.value,
                "command": cmd_clean,
                "shell": shell_clean,
                "message": f"Command timed out after {run_timeout}s.",
            }
        except Exception as exc:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "duration_ms": 0.0,
                "risk_level": report.risk_level.value,
                "command": cmd_clean,
                "shell": shell_clean,
                "message": f"Execution error: {exc}",
            }
