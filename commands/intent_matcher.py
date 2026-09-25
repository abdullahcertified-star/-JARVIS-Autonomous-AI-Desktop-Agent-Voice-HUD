"""Natural Language Intent Matching & Parameter Extraction Engine for Windows Commands.

Maps freeform natural language queries to validated Windows CMD and PowerShell commands,
extracts dynamic parameters (ports, PIDs, file paths, hostnames, app names),
and enforces the 4-tier risk classification.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from commands.database import get_command_db
from commands.executor import CommandExecutor
from commands.interpreter import ResultInterpreter
from commands.safety import RiskLevel, SafetyEngine, SafetyReport


@dataclass
class CommandIntent:
    intent_name: str
    command: str
    shell: str
    risk_level: RiskLevel
    requires_admin: bool
    destructive: bool
    requires_confirmation: bool
    confirmation_prompt: Optional[str] = None
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""


class IntentMatcher:
    """Matches natural language requests to structured Windows commands."""

    def __init__(self) -> None:
        self.db = get_command_db()
        self.desktop_dir = str(Path.home() / "Desktop")

    def match(self, user_request: str) -> CommandIntent:
        """Parses natural-language text and resolves the best matching CommandIntent."""
        text = (user_request or "").strip()
        lowered = text.lower()

        # 1. Port Process Lookup: "find which process is using port 5000", "check port 8080", "port 5000"
        port_m = re.search(r"\bport\s*[:\s]?\s*(\d{1,5})\b", lowered)
        if port_m or "port" in lowered and re.search(r"\b\d{2,5}\b", lowered):
            port = port_m.group(1) if port_m else re.search(r"\b\d{2,5}\b", lowered).group(0)
            cmd = f"netstat -ano | findstr :{port}"
            return self._build_intent(
                intent_name="PORT_PROCESS_LOOKUP",
                command=cmd,
                shell="cmd",
                parameters={"port": int(port)},
                description=f"Find processes listening on TCP/UDP port {port}",
            )

        # 2. IP & Network Configuration
        if any(k in lowered for k in ("flush dns", "clear dns cache", "reset dns")):
            return self._build_intent(
                intent_name="NETWORK_FLUSH_DNS",
                command="ipconfig /flushdns",
                shell="cmd",
                description="Flush the Windows DNS Resolver Cache",
            )

        if any(k in lowered for k in ("detailed ip", "detailed network", "ipconfig all", "show all network config")):
            return self._build_intent(
                intent_name="NETWORK_IP_DETAILED",
                command="ipconfig /all",
                shell="cmd",
                description="Display detailed TCP/IP network configuration",
            )

        if re.search(r"\b(?:what(?:'s| is)|show|check|display|get)\s+(?:my\s+)?(?:local\s+)?ip\b", lowered) or lowered in ("ipconfig", "show my ip", "my ip"):
            return self._build_intent(
                intent_name="NETWORK_IP_LOOKUP",
                command="ipconfig",
                shell="cmd",
                description="Display current IP configuration",
            )

        # 3. Internet Connectivity / Ping: "check my internet", "test internet connectivity", "ping 8.8.8.8"
        if any(k in lowered for k in ("check my internet", "test internet", "is internet working", "check connection")):
            return self._build_intent(
                intent_name="INTERNET_CONNECTIVITY_TEST",
                command="ping -n 4 8.8.8.8",
                shell="cmd",
                parameters={"host": "8.8.8.8"},
                description="Test internet connectivity to Google DNS",
            )

        ping_m = re.search(r"\bping\s+([a-zA-Z0-9.\-]+)\b", lowered)
        if ping_m:
            host = ping_m.group(1).strip()
            return self._build_intent(
                intent_name="NETWORK_PING",
                command=f"ping -n 4 {host}",
                shell="cmd",
                parameters={"host": host},
                description=f"Ping host {host}",
            )

        # 4. Running Processes: "show me all running processes", "what programs are running", "tasklist"
        if any(k in lowered for k in ("running processes", "what programs are running", "show processes", "list tasks", "tasklist", "active processes")):
            return self._build_intent(
                intent_name="PROCESS_LIST",
                command="tasklist",
                shell="cmd",
                description="List all currently active Windows tasks and processes",
            )

        # 5. Process Termination / Kill: "kill process 1234", "kill Chrome", "terminate process 5000"
        kill_pid_m = re.search(r"\b(?:kill|terminate|stop|end)\s+(?:process|pid|task)\s+(\d+)\b", lowered)
        if kill_pid_m:
            pid = kill_pid_m.group(1)
            return self._build_intent(
                intent_name="PROCESS_KILL_PID",
                command=f"taskkill /PID {pid} /F",
                shell="cmd",
                parameters={"pid": int(pid)},
                description=f"Forcefully terminate process with PID {pid}",
            )

        kill_app_m = re.search(r"\b(?:kill|terminate|force\s+close)\s+([a-zA-Z0-9_\-]+)\b", lowered)
        if kill_app_m and kill_app_m.group(1) not in ("process", "pid", "task", "app", "application"):
            app_name = kill_app_m.group(1)
            clean_app = app_name if app_name.endswith(".exe") else f"{app_name}.exe"
            return self._build_intent(
                intent_name="PROCESS_KILL_NAME",
                command=f"taskkill /IM {clean_app} /F",
                shell="cmd",
                parameters={"process_name": clean_app},
                description=f"Forcefully terminate process {clean_app}",
            )

        # 6. Folder Creation: "create a folder called Projects on my desktop", "make a folder Test"
        folder_m = re.search(r"\b(?:create|make)\s+(?:a\s+)?(?:folder|directory)(?:\s+called)?\s+([a-zA-Z0-9_\-\s]+?)(?:\s+on\s+my\s+desktop|\s+on\s+desktop|$)", text, re.IGNORECASE)
        if folder_m:
            raw_name = folder_m.group(1).strip()
            # Clean trailing words
            raw_name = re.sub(r"\s+on\s+(?:my\s+)?desktop.*$", "", raw_name, flags=re.IGNORECASE).strip()
            if not raw_name:
                raw_name = "New Folder"

            is_desktop = "desktop" in lowered
            target_path = os.path.join(self.desktop_dir, raw_name) if is_desktop else raw_name

            return self._build_intent(
                intent_name="DIRECTORY_CREATE",
                command=f'mkdir "{target_path}"',
                shell="cmd",
                parameters={"name": raw_name, "path": target_path},
                description=f"Create directory '{raw_name}'",
            )

        # 7. System Info & Windows Version
        if any(k in lowered for k in ("system information", "system specs", "hardware specs")):
            return self._build_intent(
                intent_name="SYSTEM_INFO",
                command="systeminfo",
                shell="cmd",
                description="Display detailed Windows system information",
            )

        if any(k in lowered for k in ("windows version", "os version", "what version of windows")):
            return self._build_intent(
                intent_name="WINDOWS_VERSION",
                command="ver",
                shell="cmd",
                description="Display Windows operating system version",
            )

        # 8. Executable Lookup: "find Python", "where is node installed"
        where_m = re.search(r"\b(?:find|where is|locate)\s+([a-zA-Z0-9_\-]+)(?:\s+executable|\s+installed)?\b", lowered)
        if where_m and where_m.group(1) not in ("my", "the", "a", "process", "port", "folder", "file"):
            prog = where_m.group(1).strip()
            return self._build_intent(
                intent_name="EXECUTABLE_LOOKUP",
                command=f"where {prog}",
                shell="cmd",
                parameters={"program": prog},
                description=f"Locate executable path for '{prog}'",
            )

        # 9. Network Adapters: "show network adapters", "list network interfaces"
        if any(k in lowered for k in ("network adapter", "network interface", "network cards")):
            return self._build_intent(
                intent_name="NETWORK_ADAPTER_LIST",
                command="Get-NetAdapter",
                shell="cmd",  # Invoked via powershell when executed
                description="List physical and virtual network adapters",
            )

        # 10. Windows Services: "show Windows services", "list services"
        if any(k in lowered for k in ("windows service", "list services", "system services")):
            return self._build_intent(
                intent_name="SERVICE_LIST",
                command="Get-Service",
                shell="powershell",
                description="List Windows services and their running status",
            )

        # 11. Explicit Dangerous Requests
        if "format" in lowered and re.search(r"\b[a-zA-Z]:", lowered):
            drive_m = re.search(r"\b([a-zA-Z]):", lowered)
            drive = drive_m.group(1).upper() if drive_m else "D"
            return self._build_intent(
                intent_name="DISK_FORMAT",
                command=f"format {drive}: /q",
                shell="cmd",
                parameters={"drive": drive},
                description=f"Format volume {drive}:",
            )

        if any(k in lowered for k in ("disable firewall", "turn off firewall")):
            return self._build_intent(
                intent_name="FIREWALL_DISABLE",
                command="netsh advfirewall set allprofiles state off",
                shell="cmd",
                description="Disable all Windows Firewall profiles",
            )

        if "delete registry" in lowered or "remove registry" in lowered:
            return self._build_intent(
                intent_name="REGISTRY_DELETE",
                command="reg delete HKCU\\Software\\JarvisTestKey /f",
                shell="cmd",
                description="Delete Windows Registry key",
            )

        if "delete this folder" in lowered or "delete folder" in lowered:
            return self._build_intent(
                intent_name="FOLDER_DELETE",
                command='rd /s /q "C:\\Temp\\TargetFolder"',
                shell="cmd",
                description="Delete folder tree",
            )

        # 12. Fallback to Command Knowledge Base Search
        matches = self.db.search(text, limit=1)
        if matches:
            top = matches[0]
            shell = top.get("shell", "cmd")
            cmd = top.get("template", top["clean_name"]).replace("{args}", "").strip()
            return self._build_intent(
                intent_name=f"KB_{top['clean_name'].upper()}",
                command=cmd or top["clean_name"],
                shell=shell,
                description=top.get("description", ""),
            )

        # Default fallback
        return self._build_intent(
            intent_name="UNKNOWN",
            command=text,
            shell="cmd",
            description="Unrecognized command intent",
        )

    def _build_intent(
        self,
        intent_name: str,
        command: str,
        shell: str,
        parameters: Optional[dict[str, Any]] = None,
        description: str = "",
    ) -> CommandIntent:
        """Evaluates safety and creates a structured CommandIntent."""
        report = SafetyEngine.analyze(command, shell)
        return CommandIntent(
            intent_name=intent_name,
            command=command,
            shell=shell,
            risk_level=report.risk_level,
            requires_admin=report.requires_admin,
            destructive=report.destructive,
            requires_confirmation=report.requires_confirmation,
            confirmation_prompt=report.confirmation_prompt,
            parameters=parameters or {},
            description=description or report.reason,
        )

    def execute_request(self, user_request: str, confirmed: bool = False) -> dict[str, Any]:
        """Translates natural language request, validates safety, executes, and interprets output."""
        intent = self.match(user_request)

        # If confirmation is required and user hasn't explicitly confirmed
        if intent.requires_confirmation and not confirmed:
            return {
                "success": False,
                "requires_confirmation": True,
                "risk_level": intent.risk_level.value,
                "intent": intent.intent_name,
                "command": intent.command,
                "shell": intent.shell,
                "parameters": intent.parameters,
                "message": intent.confirmation_prompt or f"This command is classified as {intent.risk_level.value} risk. Do you want to proceed?",
                "response": intent.confirmation_prompt or f"This command is classified as {intent.risk_level.value} risk. Do you want to proceed?",
            }

        # Safe execution
        result = CommandExecutor.execute(
            command=intent.command,
            shell=intent.shell,
            confirmed=confirmed,
        )

        # Natural language interpretation of stdout/stderr
        spoken_response = ResultInterpreter.interpret(intent.command, result)

        # For lookup commands (e.g. findstr / where), an exit code of 1 with no stderr indicates normal 'no match' result
        is_success = result.get("success", False)
        if intent.intent_name == "PORT_PROCESS_LOOKUP" and result.get("exit_code") in (0, 1) and not result.get("stderr"):
            is_success = True
        elif intent.intent_name == "EXECUTABLE_LOOKUP" and result.get("exit_code") in (0, 1):
            is_success = True

        return {
            "success": is_success,
            "intent": intent.intent_name,
            "command": intent.command,
            "shell": intent.shell,
            "exit_code": result.get("exit_code", 0),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "duration_ms": result.get("duration_ms", 0),
            "risk_level": intent.risk_level.value,
            "response": spoken_response,
            "message": spoken_response,
        }
