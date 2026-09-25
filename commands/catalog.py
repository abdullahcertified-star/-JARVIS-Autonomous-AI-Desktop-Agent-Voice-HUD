"""Extracts, enriches, and structures all commands from the Windows Command Master Reference PDF.

Covers the 13 major families (492 cataloged commands):
1. File & Directory
2. System & Information
3. Networking
4. Processes, Services & Tasks
5. Users, Groups & Security
6. Disk, Storage & Recovery
7. Windows Repair & Administration
8. CMD Shell & Batch Scripting
9. PowerShell Core / Windows PowerShell
10. Developer & Git
11. Windows Package & App Management
12. Diagnostics, Logs & Performance
13. Windows Scripting / Legacy Utilities
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pypdf

# Default PDF path
DEFAULT_PDF_PATH = Path(r"C:\Users\Abdullah_\Desktop\Jarvis_Windows_Command_Master_Reference.pdf")

# Standard Master Categories
MASTER_CATEGORIES = [
    "File & Directory",
    "System & Information",
    "Networking",
    "Processes, Services & Tasks",
    "Users, Groups & Security",
    "Disk, Storage & Recovery",
    "Windows Repair & Administration",
    "CMD Shell & Batch Scripting",
    "PowerShell Core / Windows PowerShell",
    "Developer & Git",
    "Windows Package & App Management",
    "Diagnostics, Logs & Performance",
    "Windows Scripting / Legacy Utilities",
]

# Risk classification keywords and rules
_CRITICAL_COMMANDS = {
    "format", "diskpart", "bcdedit", "bcdboot", "bootrec", "reagentc",
    "format-volume", "initialize-disk", "repair-bde", "ntdsutil",
    "dism /online /cleanup-image /restorehealth", "chkdsk /r",
}

_HIGH_COMMANDS = {
    "del", "erase", "rd", "rmdir", "remove-item", "taskkill", "stop-process",
    "icacls", "takeown", "net user", "net localgroup", "net accounts",
    "reg add", "reg delete", "reg import", "cipher", "manage-bde",
    "set-acl", "disable-netfirewallrule", "disable-windowsoptionalfeature",
    "remove-appxpackage", "remove-localuser", "remove-localgroupmember",
    "stop-service", "sc stop", "sc config", "logoff", "shutdown", "vssadmin",
}

_MEDIUM_COMMANDS = {
    "mkdir", "md", "new-item", "copy", "move", "ren", "rename", "xcopy",
    "robocopy", "copy-item", "move-item", "rename-item", "set-content",
    "add-content", "restart-service", "restart-computer", "winget install",
    "winget upgrade", "winget uninstall", "npm install", "pip install",
    "git commit", "git push", "git checkout", "git merge", "git rebase",
    "git reset", "git stash", "setx", "schtasks /create", "schtasks /delete",
    "sc start", "start-service", "set-service", "new-partition",
    "resize-partition", "enable-windowsoptionalfeature", "add-appxpackage",
    "add-windowsoptionalfeature", "install-module", "update-module",
}

_ADMIN_COMMANDS = {
    "sfc", "dism", "bcdedit", "bcdboot", "bootrec", "diskpart", "format",
    "chkdsk", "sc", "netsh advfirewall", "icacls", "takeown", "manage-bde",
    "reagentc", "auditpol", "vssadmin", "wbadmin", "net user", "net localgroup",
    "enable-windowsoptionalfeature", "disable-windowsoptionalfeature",
    "initialize-disk", "new-partition", "format-volume", "resize-partition",
    "set-executionpolicy", "secpol.msc", "gpedit.msc", "defrag", "fsutil",
    "gpupdate", "netsh", "net accounts",
}

_DESTRUCTIVE_COMMANDS = {
    "del", "erase", "rd", "rmdir", "remove-item", "format", "diskpart",
    "format-volume", "taskkill", "stop-process", "reg delete", "remove-localuser",
    "remove-localgroupmember", "remove-appxpackage",
}

# Domain dictionaries for enriched descriptions & examples
COMMAND_METADATA: dict[str, dict[str, Any]] = {
    "ipconfig": {
        "description": "Displays all current TCP/IP network configuration values, refresh DHCP and DNS settings.",
        "examples": ["ipconfig", "ipconfig /all", "ipconfig /flushdns", "ipconfig /release", "ipconfig /renew"],
        "template": "ipconfig {args}",
        "intents": [
            "what is my IP",
            "show my IP address",
            "check my IP",
            "show network configuration",
            "display IP settings",
            "show detailed network info",
            "flush DNS",
            "renew my IP address",
        ],
    },
    "netstat": {
        "description": "Displays active TCP connections, listening ports, network statistics, and process identifiers.",
        "examples": ["netstat -ano", "netstat -ano | findstr :5000", "netstat -e", "netstat -r"],
        "template": "netstat {args}",
        "intents": [
            "find which process is using port {port}",
            "show listening ports",
            "check port {port}",
            "what is running on port {port}",
            "show all open ports",
            "display active network connections",
            "which app is using port {port}",
        ],
    },
    "tasklist": {
        "description": "Displays a list of currently running applications, background services, and process IDs (PIDs).",
        "examples": ["tasklist", "tasklist /v", 'tasklist /fi "STATUS eq RUNNING"', "tasklist /m"],
        "template": "tasklist {args}",
        "intents": [
            "show me all running processes",
            "what programs are running",
            "list running tasks",
            "show running applications",
            "check active processes",
            "view background tasks",
        ],
    },
    "taskkill": {
        "description": "Terminates tasks or processes by process ID (PID) or executable image name.",
        "examples": ["taskkill /PID {pid} /F", "taskkill /IM {process_name} /F"],
        "template": "taskkill {args}",
        "intents": [
            "kill process {pid}",
            "terminate process {pid}",
            "stop task {process_name}",
            "kill {process_name}",
            "force close {process_name}",
            "end process {pid}",
        ],
    },
    "ping": {
        "description": "Verifies IP-level connectivity to another computer or domain by sending ICMP Echo messages.",
        "examples": ["ping 8.8.8.8", "ping google.com", "ping -n 4 1.1.1.1"],
        "template": "ping {args}",
        "intents": [
            "test internet connectivity",
            "check my internet",
            "ping google.com",
            "check if {host} is online",
            "test connection to {host}",
            "is the internet working",
        ],
    },
    "systeminfo": {
        "description": "Displays detailed operating system and machine hardware configuration, BIOS, OS version, and hotfixes.",
        "examples": ["systeminfo"],
        "template": "systeminfo",
        "intents": [
            "show system information",
            "display system specs",
            "what version of Windows is this",
            "show OS details and specs",
            "view hardware and OS configuration",
        ],
    },
    "dir": {
        "description": "Displays a list of files and subdirectories in a directory.",
        "examples": ["dir", "dir /w", "dir /od", "dir /s"],
        "template": "dir {args}",
        "intents": [
            "list files in this directory",
            "show directory contents",
            "list folder items",
            "what files are in this folder",
        ],
    },
    "mkdir": {
        "description": "Creates a directory or subdirectory.",
        "examples": ['mkdir "{path}"', 'mkdir Projects'],
        "template": 'mkdir "{path}"',
        "intents": [
            "create a folder called {name}",
            "make a new directory called {name}",
            "create folder {name} on my desktop",
            "make folder {path}",
        ],
    },
    "Get-Process": {
        "description": "Gets the processes that are running on the local computer with resource consumption stats.",
        "examples": ["Get-Process", "Get-Process -Name chrome", "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10"],
        "template": "Get-Process {args}",
        "intents": [
            "show PowerShell running processes",
            "find top CPU consuming processes",
            "get process details for {name}",
            "list processes using PowerShell",
        ],
    },
    "Get-Service": {
        "description": "Gets the Windows services on the computer and their current running status.",
        "examples": ["Get-Service", "Get-Service | Where-Object {$_.Status -eq 'Running'}", "Get-Service -Name wuauserv"],
        "template": "Get-Service {args}",
        "intents": [
            "show Windows services",
            "list running services",
            "check status of service {service_name}",
            "view all system services",
        ],
    },
    "Get-NetTCPConnection": {
        "description": "Gets current TCP connections, local/remote addresses, ports, and owning process IDs in PowerShell.",
        "examples": ["Get-NetTCPConnection", "Get-NetTCPConnection -LocalPort {port}", "Get-NetTCPConnection -State Listen"],
        "template": "Get-NetTCPConnection {args}",
        "intents": [
            "find process on port {port} using PowerShell",
            "check TCP connections on port {port}",
            "show listening TCP connections",
        ],
    },
    "Get-NetAdapter": {
        "description": "Gets basic network adapter properties and interface status.",
        "examples": ["Get-NetAdapter", "Get-NetAdapter -Name *", "Get-NetAdapter | Where-Object Status -eq 'Up'"],
        "template": "Get-NetAdapter {args}",
        "intents": [
            "show network adapters",
            "list network interfaces",
            "check network card status",
            "view active network adapters",
        ],
    },
    "Test-NetConnection": {
        "description": "Displays diagnostic information for a connection, tests ping, TCP port connectivity, and route tracing.",
        "examples": ["Test-NetConnection -ComputerName google.com", "Test-NetConnection -ComputerName 127.0.0.1 -Port 80"],
        "template": "Test-NetConnection {args}",
        "intents": [
            "test network connection to {host}",
            "test if port {port} is open on {host}",
            "check connectivity with Test-NetConnection",
        ],
    },
    "sfc": {
        "description": "Scans and verifies the integrity of all protected system files and replaces corrupted versions.",
        "examples": ["sfc /scannow", "sfc /verifyonly"],
        "template": "sfc {args}",
        "intents": [
            "scan and repair system files",
            "run SFC scan",
            "fix corrupted Windows files",
            "check Windows system file integrity",
        ],
    },
    "dism": {
        "description": "Deployment Image Servicing and Management tool to repair Windows images, component stores, and features.",
        "examples": ["DISM /Online /Cleanup-Image /ScanHealth", "DISM /Online /Cleanup-Image /RestoreHealth"],
        "template": "dism {args}",
        "intents": [
            "repair Windows component store",
            "run DISM health scan",
            "restore Windows system health",
            "repair Windows image",
        ],
    },
    "where": {
        "description": "Locates and displays the path of specified executables or files matching the pattern.",
        "examples": ["where python", "where node", "where git"],
        "template": "where {name}",
        "intents": [
            "find python executable",
            "where is {program} installed",
            "locate path of {program}",
            "find executable for {program}",
        ],
    },
    "winget": {
        "description": "Windows Package Manager command line tool to discover, install, upgrade, and configure applications.",
        "examples": ["winget search {app}", "winget install {app}", "winget upgrade --all", "winget list"],
        "template": "winget {args}",
        "intents": [
            "search for app {app} with winget",
            "install {app} using winget",
            "upgrade all installed packages",
            "list installed winget packages",
        ],
    },
    "whoami": {
        "description": "Displays the user name and domain of the currently logged-on user.",
        "examples": ["whoami", "whoami /all", "whoami /priv", "whoami /groups"],
        "template": "whoami {args}",
        "intents": [
            "who am I",
            "what is my username",
            "show current user account",
            "check user privileges and groups",
        ],
    },
    "hostname": {
        "description": "Prints the computer name / host name of the current Windows system.",
        "examples": ["hostname"],
        "template": "hostname",
        "intents": [
            "what is my computer name",
            "show machine hostname",
            "display PC name",
        ],
    },
    "git": {
        "description": "Git distributed version control system.",
        "examples": ["git status", "git log -n 5", "git branch", "git pull", "git push"],
        "template": "git {args}",
        "intents": [
            "check git status",
            "show recent git commits",
            "list git branches",
            "pull latest changes",
        ],
    },
}


def clean_raw_command(raw: str) -> tuple[str, str, str]:
    """Cleans a raw command string from the PDF into (clean_name, shell_hint, extra_info)."""
    text = raw.strip()

    # Detect explicit shell tag like (PowerShell) or (cmd)
    shell = "cmd"
    if "(powershell)" in text.lower():
        shell = "powershell"
        text = re.sub(r"\(PowerShell\)", "", text, flags=re.IGNORECASE).strip()

    if "(external)" in text.lower():
        text = re.sub(r"\(external\)", "", text, flags=re.IGNORECASE).strip()

    extra = ""
    if "(" in text and text.endswith(")"):
        m = re.search(r"\((.*?)\)$", text)
        if m:
            extra = m.group(1).strip()
            text = text[:m.start()].strip()

    # PowerShell noun-verb heuristic (e.g. Get-Process, Test-NetConnection)
    if re.match(r"^[A-Z][a-zA-Z0-9]+-[A-Z][a-zA-Z0-9]+$", text):
        shell = "powershell"

    return text, shell, extra


def determine_risk(clean_cmd: str, category: str) -> tuple[str, bool, bool]:
    """Determines (risk_level, requires_admin, destructive) for a command."""
    lowered = clean_cmd.lower().strip()
    cmd_head = lowered.split()[0] if lowered else ""

    # Check CRITICAL
    if lowered in _CRITICAL_COMMANDS or cmd_head in _CRITICAL_COMMANDS:
        return "CRITICAL", True, True
    if any(k in lowered for k in ("format", "diskpart", "bcdedit", "bootrec", "initialize-disk")):
        return "CRITICAL", True, True

    # Check HIGH
    if lowered in _HIGH_COMMANDS or cmd_head in _HIGH_COMMANDS:
        is_dest = cmd_head in _DESTRUCTIVE_COMMANDS or any(k in lowered for k in ("del", "rmdir", "erase", "taskkill", "kill"))
        is_admin = cmd_head in _ADMIN_COMMANDS or "admin" in category.lower()
        return "HIGH", is_admin, is_dest
    if any(k in lowered for k in ("taskkill", "stop-process", "reg delete", "remove-item", "del ", "rmdir ")):
        return "HIGH", True, True

    # Check MEDIUM
    if lowered in _MEDIUM_COMMANDS or cmd_head in _MEDIUM_COMMANDS:
        is_admin = cmd_head in _ADMIN_COMMANDS
        return "MEDIUM", is_admin, False
    if any(k in lowered for k in ("install", "mkdir", "copy", "move", "rename", "new-item", "restart-")):
        return "MEDIUM", False, False

    # Default to LOW for read-only / diagnostic utilities
    is_admin = cmd_head in _ADMIN_COMMANDS
    return "LOW", is_admin, False


def extract_commands_from_pdf(pdf_path: Path | str = DEFAULT_PDF_PATH) -> list[dict[str, Any]]:
    """Reads the PDF file and returns all 492 structured command dictionaries."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found at {path}")

    reader = pypdf.PdfReader(str(path))
    full_text = ""
    for i, page in enumerate(reader.pages):
        full_text += f"\n=== PAGE {i+1} ===\n" + (page.extract_text() or "")

    lines = [l.strip() for l in full_text.splitlines()]

    raw_items: list[tuple[int, str, str]] = []
    curr_cat = MASTER_CATEGORIES[0]
    i = 0
    while i < len(lines):
        line = lines[i]
        for c in MASTER_CATEGORIES:
            if line.startswith(c):
                curr_cat = c
                break

        if line.isdigit():
            num = int(line)
            j = i + 1
            cmd_text = []
            while j < len(lines):
                cand = lines[j]
                if cand.startswith("=== PAGE") or cand.startswith("Jarvis Windows Command") or cand.startswith("Page "):
                    j += 1
                    continue
                if any(cand.startswith(c) for c in MASTER_CATEGORIES):
                    curr_cat = [c for c in MASTER_CATEGORIES if cand.startswith(c)][0]
                    j += 1
                    continue
                if cand.isdigit() or cand.startswith("How to expand"):
                    break
                cmd_text.append(cand)
                j += 1
                if j < len(lines) and (lines[j].isdigit() or any(lines[j].startswith(c) for c in MASTER_CATEGORIES)):
                    break
            cmd_str = " ".join(cmd_text).strip()
            raw_items.append((num, curr_cat, cmd_str))
            i = j - 1
        i += 1

    catalog: list[dict[str, Any]] = []

    for num, category, raw_str in raw_items:
        clean_name, shell_hint, extra = clean_raw_command(raw_str)

        # Force shell for PowerShell category
        if "powershell" in category.lower():
            shell = "powershell"
        else:
            shell = shell_hint

        risk, requires_admin, destructive = determine_risk(clean_name, category)

        # Fetch custom metadata if available, else generate default structured info
        meta = COMMAND_METADATA.get(clean_name, {})
        description = meta.get("description")
        if not description:
            if shell == "powershell":
                description = f"PowerShell cmdlet for {clean_name} under {category}."
            else:
                description = f"Windows command utility for {clean_name} ({category})."

        examples = meta.get("examples", [clean_name])
        template = meta.get("template", f"{clean_name} {{args}}")
        intents = meta.get("intents", [
            f"run {clean_name}",
            f"execute {clean_name}",
            f"how to use {clean_name}",
            f"show {clean_name} info",
        ])

        item: dict[str, Any] = {
            "id": num,
            "raw_command": raw_str,
            "command": clean_name,
            "clean_name": clean_name,
            "category": category,
            "shell": shell,
            "description": description,
            "examples": examples,
            "risk_level": risk,
            "requires_admin": requires_admin,
            "destructive": destructive,
            "template": template,
            "intents": intents,
            "extra_info": extra,
        }
        catalog.append(item)

    return catalog


def build_and_save_catalog(
    pdf_path: Path | str = DEFAULT_PDF_PATH,
    output_json_path: Path | str = "database/commands.json",
) -> list[dict[str, Any]]:
    """Extracts all commands and writes the JSON catalog."""
    catalog = extract_commands_from_pdf(pdf_path)
    out_p = Path(output_json_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    return catalog
