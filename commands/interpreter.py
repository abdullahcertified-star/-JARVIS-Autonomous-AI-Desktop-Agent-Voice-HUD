"""Natural Language Result Interpreter for CLI Outputs.

Transforms raw stdout/stderr from Windows CLI and PowerShell commands into
crisp, elegant, voice-ready spoken responses.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import psutil


class ResultInterpreter:
    """Interprets raw command execution outputs into concise natural language."""

    @classmethod
    def interpret(cls, command: str, result: dict[str, Any]) -> str:
        """Interprets execution result into a natural-language sentence."""
        stdout = (result.get("stdout") or "").strip()
        stderr = (result.get("stderr") or "").strip()
        exit_code = result.get("exit_code", 0)
        success = result.get("success", False)
        cmd_lower = command.lower().strip()

        # Handle blocked / confirmation required responses
        if result.get("requires_confirmation"):
            return result.get("message", "Confirmation required before executing this command.")

        # Special case: findstr returns 1 when no pattern matches (which means port is free)
        if "findstr" in cmd_lower and exit_code == 1 and not stderr:
            port_match = re.search(r":(\d+)", command)
            port_str = port_match.group(1) if port_match else "specified port"
            return f"Positive sir, port {port_str} is currently free and not in use by any process."

        # If execution failed
        if not success:
            err_msg = stderr or stdout or result.get("message", "Command execution failed")
            first_err = err_msg.splitlines()[0] if err_msg.splitlines() else err_msg
            return f"Negative sir, command failed ({first_err.strip()})."

        # 1. Netstat port lookup: netstat -ano | findstr :<port>
        if "netstat" in cmd_lower and "findstr" in cmd_lower:
            port_match = re.search(r":(\d+)", command)
            port_str = port_match.group(1) if port_match else "specified port"
            if not stdout:
                return f"Positive sir, port {port_str} is currently free and not in use by any process."

            lines = stdout.splitlines()
            pids = set()
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    pids.add(int(parts[-1]))

            if pids:
                pid_info = []
                for pid in sorted(pids):
                    proc_name = "Unknown"
                    try:
                        proc = psutil.Process(pid)
                        proc_name = proc.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    pid_info.append(f"PID {pid} ({proc_name})")

                return f"Positive sir, port {port_str} is being used by {', '.join(pid_info)}."
            return f"Positive sir, port {port_str} is active: {lines[0].strip()}."

        # 2. IPConfig / network info
        if "ipconfig" in cmd_lower:
            if "flushdns" in cmd_lower:
                return "Positive sir, Windows DNS Resolver Cache has been successfully flushed."

            ipv4_matches = re.findall(r"IPv4 Address[.\s]*:\s*([0-9.]+)", stdout)
            gateway_matches = re.findall(r"Default Gateway[.\s]*:\s*([0-9.]+)", stdout)

            if ipv4_matches:
                ip_str = ipv4_matches[0]
                gw_str = f" with default gateway {gateway_matches[0]}" if gateway_matches else ""
                return f"Positive sir, your local IP address is {ip_str}{gw_str}."
            return "Positive sir, network configuration retrieved."

        # 3. Ping
        if cmd_lower.startswith("ping"):
            target_match = re.search(r"ping\s+.*?([a-zA-Z0-9.\-]+)(?:\s|$)", command)
            target = target_match.group(1) if target_match else "host"
            time_m = re.search(r"Average\s*=\s*(\d+ms)", stdout)
            loss_m = re.search(r"(\d+)%\s*loss", stdout)

            if "100% loss" in stdout or "could not find host" in stdout.lower() or "timed out" in stdout.lower():
                return f"Negative sir, {target} is unreachable."

            avg_str = f" with an average latency of {time_m.group(1)}" if time_m else ""
            loss_str = f" ({loss_m.group(1)}% packet loss)" if loss_m and loss_m.group(1) != "0" else ""
            return f"Positive sir, ping to {target} succeeded{avg_str}{loss_str}."

        # 4. Tasklist / Running processes
        if cmd_lower.startswith("tasklist"):
            lines = [l for l in stdout.splitlines() if l.strip() and not l.startswith("Image Name") and not l.startswith("===")]
            count = len(lines)
            sample = [l.split()[0] for l in lines[:5]]
            return f"Positive sir, there are {count} active tasks running, including {', '.join(sample)}."

        # 5. Whoami
        if cmd_lower.startswith("whoami"):
            user_clean = stdout.strip()
            return f"Positive sir, the current user identity is {user_clean}."

        # 6. Hostname
        if cmd_lower.startswith("hostname"):
            return f"Positive sir, your computer hostname is {stdout.strip()}."

        # 7. Systeminfo
        if cmd_lower.startswith("systeminfo"):
            os_name = re.search(r"OS Name:\s*(.+)", stdout)
            os_ver = re.search(r"OS Version:\s*(.+)", stdout)
            total_ram = re.search(r"Total Physical Memory:\s*(.+)", stdout)
            parts = []
            if os_name:
                parts.append(os_name.group(1).strip())
            if os_ver:
                parts.append(os_ver.group(1).strip())
            if total_ram:
                parts.append(f"RAM: {total_ram.group(1).strip()}")
            summary = ", ".join(parts) if parts else "System information retrieved"
            return f"Positive sir, {summary}."

        # 8. Where executable lookup
        if cmd_lower.startswith("where"):
            paths = [l.strip() for l in stdout.splitlines() if l.strip()]
            if paths:
                return f"Positive sir, located executable at {paths[0]}."
            return "Negative sir, executable not found in PATH."

        # 9. Directory creation / mkdir
        if cmd_lower.startswith("mkdir") or cmd_lower.startswith("md"):
            return "Positive sir, folder created successfully."

        # 10. Process termination / taskkill
        if cmd_lower.startswith("taskkill") or "stop-process" in cmd_lower:
            return "Positive sir, target process has been terminated."

        # 11. PowerShell Get-Service / Get-Process
        if "get-service" in cmd_lower:
            lines = [l.strip() for l in stdout.splitlines() if l.strip() and not l.startswith("Status")]
            return f"Positive sir, retrieved {len(lines)} system services."

        if "get-process" in cmd_lower:
            lines = [l.strip() for l in stdout.splitlines() if l.strip() and not l.startswith("Handles")]
            return f"Positive sir, retrieved {len(lines)} active processes."

        # Fallback for general commands: take first clean non-empty line
        clean_lines = [l.strip() for l in stdout.splitlines() if l.strip()]
        if clean_lines:
            first_line = clean_lines[0]
            if len(first_line) > 160:
                first_line = first_line[:160] + "..."
            return f"Positive sir, {first_line}"

        return "Positive sir, command completed successfully."
