"""Safety and Risk Classification Engine for Windows Command Execution.

Enforces a 4-tier risk policy:
- LOW: Diagnostic, informational, read-only commands. Execute immediately.
- MEDIUM: Package management, harmless service restarts, directory creations.
- HIGH: Process termination, file deletions, permission changes, registry edits.
        MUST require explicit user confirmation before execution.
- CRITICAL: Disk formatting, partition wiping, boot configuration altering, recursive root deletion.
        STRICTLY requires explicit user confirmation and high-scrutiny validation.
"""

from __future__ import annotations

import enum
import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Optional


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class SafetyReport:
    command: str
    shell: str
    risk_level: RiskLevel
    requires_admin: bool
    destructive: bool
    requires_confirmation: bool
    confirmation_prompt: Optional[str] = None
    reason: str = ""
    is_safe_to_execute: bool = True


# Explicit blacklists & high-danger pattern matchers
CRITICAL_PATTERNS = [
    (re.compile(r"\bformat\b\s+[a-zA-Z]:", re.IGNORECASE), "Disk formatting will erase all data on the target drive."),
    (re.compile(r"\bdiskpart\b", re.IGNORECASE), "Diskpart can wipe disks and alter volume partitions."),
    (re.compile(r"\bbcdedit\b", re.IGNORECASE), "BCDedit modifies Windows boot configuration."),
    (re.compile(r"\bbootrec\b", re.IGNORECASE), "Bootrec modifies master boot records."),
    (re.compile(r"\breagentc\b", re.IGNORECASE), "ReAgentC configures Windows Recovery Environment."),
    (re.compile(r"\b(rd|rmdir)\b\s+.*[/\\](?:s|q)", re.IGNORECASE), "Recursive directory deletion permanently erases folder trees."),
    (re.compile(r"\bdel\b\s+.*[/\\](?:s|f|q)", re.IGNORECASE), "Forced recursive file deletion."),
    (re.compile(r"\bRemove-Item\b\s+.*-(?:Recurse|Force)", re.IGNORECASE), "PowerShell recursive item deletion."),
    (re.compile(r"\bFormat-Volume\b", re.IGNORECASE), "PowerShell volume format."),
    (re.compile(r"\bInitialize-Disk\b", re.IGNORECASE), "PowerShell disk initialization wipes partition tables."),
    (re.compile(r"\bClear-Disk\b", re.IGNORECASE), "PowerShell clear disk."),
]

HIGH_PATTERNS = [
    (re.compile(r"\b(taskkill|Stop-Process)\b", re.IGNORECASE), "Terminating processes can cause unsaved work to be lost."),
    (re.compile(r"\b(del|erase|Remove-Item)\b", re.IGNORECASE), "Deleting files permanently."),
    (re.compile(r"\b(rd|rmdir)\b", re.IGNORECASE), "Removing directory."),
    (re.compile(r"\b(icacls|takeown|Set-Acl)\b", re.IGNORECASE), "Modifying Windows file/folder security permissions."),
    (re.compile(r"\bnetsh\s+advfirewall\b", re.IGNORECASE), "Modifying Windows Firewall configuration."),
    (re.compile(r"\bDisable-NetFirewallRule\b", re.IGNORECASE), "Disabling firewall security rule."),
    (re.compile(r"\breg\s+(add|delete|import)\b", re.IGNORECASE), "Modifying Windows Registry keys."),
    (re.compile(r"\b(sc|Set-Service)\s+.*stop\b", re.IGNORECASE), "Stopping a Windows system service."),
    (re.compile(r"\bnet\s+user\s+.*(?:/add|/delete)\b", re.IGNORECASE), "Modifying Windows user accounts."),
    (re.compile(r"\b(shutdown|restart-computer)\b", re.IGNORECASE), "Shutting down or restarting the computer."),
]

MEDIUM_PATTERNS = [
    (re.compile(r"\b(winget|npm|pip)\s+(install|uninstall|upgrade)\b", re.IGNORECASE), "Installing or modifying software packages."),
    (re.compile(r"\b(mkdir|md|New-Item)\b", re.IGNORECASE), "Creating new files or directories."),
    (re.compile(r"\b(Restart-Service)\b", re.IGNORECASE), "Restarting a service."),
    (re.compile(r"\b(copy|move|ren|rename|xcopy|robocopy)\b", re.IGNORECASE), "Copying or moving files."),
    (re.compile(r"\bgit\s+(commit|push|checkout|merge|rebase|reset)\b", re.IGNORECASE), "Modifying git repository state."),
]

# Safe pipeline targets allowed for read-only queries
SAFE_PIPE_TARGETS = {"findstr", "find", "more", "sort", "clip", "Select-String", "Where-Object", "Select-Object", "Measure-Object", "Format-Table", "Format-List"}


class SafetyEngine:
    """Evaluates commands against the safety policy, preventing arbitrary execution."""

    @staticmethod
    def is_admin_process() -> bool:
        """Checks if current python process has elevated administrator privileges."""
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @classmethod
    def analyze(cls, command: str, shell: str = "cmd") -> SafetyReport:
        cmd = command.strip()
        if not cmd:
            return SafetyReport(
                command=command,
                shell=shell,
                risk_level=RiskLevel.LOW,
                requires_admin=False,
                destructive=False,
                requires_confirmation=False,
                reason="Empty command",
                is_safe_to_execute=False,
            )

        # Check for multi-command injection patterns (&&, ;, ||) that chain execution
        # Allow safe piping | only when feeding into recognized filter utilities
        if re.search(r"(&&|\|\||;)", cmd):
            # Check if this is a benign conditional or an injection attempt
            return SafetyReport(
                command=cmd,
                shell=shell,
                risk_level=RiskLevel.HIGH,
                requires_admin=False,
                destructive=False,
                requires_confirmation=True,
                confirmation_prompt=f"This command uses chained shell execution: '{cmd}'. Do you want me to continue?",
                reason="Chained command execution requires explicit confirmation.",
            )

        # Check pipe safety
        if "|" in cmd:
            parts = cmd.split("|")
            for pipe_part in parts[1:]:
                head = pipe_part.strip().split()[0] if pipe_part.strip() else ""
                clean_head = re.sub(r"[^a-zA-Z\-]", "", head)
                if clean_head not in SAFE_PIPE_TARGETS:
                    return SafetyReport(
                        command=cmd,
                        shell=shell,
                        risk_level=RiskLevel.HIGH,
                        requires_admin=False,
                        destructive=False,
                        requires_confirmation=True,
                        confirmation_prompt=f"This command pipes output into '{clean_head}'. Do you want me to continue?",
                        reason=f"Pipe target '{clean_head}' requires explicit confirmation.",
                    )

        # 1. Evaluate CRITICAL patterns
        for pattern, desc in CRITICAL_PATTERNS:
            if pattern.search(cmd):
                return SafetyReport(
                    command=cmd,
                    shell=shell,
                    risk_level=RiskLevel.CRITICAL,
                    requires_admin=True,
                    destructive=True,
                    requires_confirmation=True,
                    confirmation_prompt=f"CRITICAL WARNING: {desc}\nCommand: `{cmd}`\nThis operation can cause severe system damage or permanent data loss. Are you absolutely certain you want to proceed?",
                    reason=desc,
                )

        # 2. Evaluate HIGH patterns
        for pattern, desc in HIGH_PATTERNS:
            if pattern.search(cmd):
                return SafetyReport(
                    command=cmd,
                    shell=shell,
                    risk_level=RiskLevel.HIGH,
                    requires_admin="permission" in desc.lower() or "firewall" in desc.lower() or "registry" in desc.lower(),
                    destructive="delete" in desc.lower() or "terminat" in desc.lower() or "remov" in desc.lower(),
                    requires_confirmation=True,
                    confirmation_prompt=f"This operation requires confirmation: {desc} Command: `{cmd}`. Do you want me to continue?",
                    reason=desc,
                )

        # 3. Evaluate MEDIUM patterns
        for pattern, desc in MEDIUM_PATTERNS:
            if pattern.search(cmd):
                return SafetyReport(
                    command=cmd,
                    shell=shell,
                    risk_level=RiskLevel.MEDIUM,
                    requires_admin=False,
                    destructive=False,
                    requires_confirmation=False,
                    reason=desc,
                )

        # 4. Default to LOW (Diagnostic / Read-only)
        return SafetyReport(
            command=cmd,
            shell=shell,
            risk_level=RiskLevel.LOW,
            requires_admin=False,
            destructive=False,
            requires_confirmation=False,
            reason="Read-only diagnostic command.",
        )

    @classmethod
    def validate_execution(
        cls,
        command: str,
        shell: str = "cmd",
        confirmed: bool = False,
    ) -> tuple[bool, Optional[str], SafetyReport]:
        """Validates command against safety rules and confirmation requirements.

        Returns: (allowed_to_run, message, report)
        """
        report = cls.analyze(command, shell)

        # If confirmation is required and user has NOT confirmed
        if report.requires_confirmation and not confirmed:
            return False, report.confirmation_prompt, report

        return True, None, report
