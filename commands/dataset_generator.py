"""Training Dataset Generator for Jarvis Windows Commands.

Expands the 492 core command references into tens of thousands of natural-language
training pairs following the pattern in Section 10 and 11 of the specification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

from commands.database import get_command_db

OUTPUT_DATASET_PATH = Path("database/jarvis_command_dataset.jsonl")

# Natural language conversational templates and prefix variations
INTENT_PREFIXES = [
    "",
    "jarvis ",
    "hey jarvis ",
    "please ",
    "can you ",
    "could you ",
    "i want to ",
    "how do i ",
    "tell me ",
    "show me ",
]

QUERY_TEMPLATES = {
    "ipconfig": [
        "what is my IP address",
        "show my IP",
        "check my IP",
        "display network configuration",
        "what network am i connected to",
        "show my IPv4 address",
        "display IP settings",
        "flush the DNS cache",
        "release my IP address",
        "renew my IP address",
    ],
    "netstat": [
        "find which process is using port {port}",
        "check port {port}",
        "what is running on port {port}",
        "who is using port {port}",
        "is port {port} open",
        "show all open ports",
        "list active TCP connections",
        "display listening ports",
    ],
    "tasklist": [
        "show me all running processes",
        "what programs are currently running",
        "list running tasks",
        "show active applications",
        "view background processes",
        "list all active tasks",
    ],
    "taskkill": [
        "kill process {pid}",
        "terminate process {pid}",
        "stop process {pid}",
        "end task {pid}",
        "force kill PID {pid}",
        "kill {process_name}",
        "terminate {process_name}",
        "force close {process_name}",
    ],
    "ping": [
        "test internet connectivity",
        "check my internet",
        "is the internet working",
        "ping {host}",
        "check connection to {host}",
        "test if {host} is reachable",
    ],
    "mkdir": [
        "create a folder called {name}",
        "make a new directory called {name}",
        "create folder {name} on my desktop",
        "make directory {name}",
        "new folder {name}",
    ],
    "systeminfo": [
        "show system information",
        "display hardware specs",
        "what version of Windows is this",
        "show OS configuration",
        "view system specifications",
    ],
    "whoami": [
        "who am I",
        "what is my username",
        "show current user",
        "display logged in user account",
    ],
    "hostname": [
        "what is my computer name",
        "show machine hostname",
        "what is the hostname of this PC",
    ],
    "where": [
        "find {program} executable",
        "where is {program} installed",
        "locate path for {program}",
        "find path of {program}",
    ],
    "Get-Process": [
        "show running processes in PowerShell",
        "get process list with PowerShell",
        "view CPU usage by process",
    ],
    "Get-Service": [
        "show Windows services",
        "list all system services",
        "check running services",
    ],
    "Get-NetAdapter": [
        "show network adapters",
        "list network interfaces",
        "check network cards",
    ],
}

SAMPLE_PORTS = [80, 443, 3000, 5000, 8000, 8080, 8443, 9000, 27017, 3306, 5432, 6379]
SAMPLE_HOSTS = ["8.8.8.8", "1.1.1.1", "google.com", "github.com", "microsoft.com", "localhost"]
SAMPLE_PIDS = [1024, 2048, 3128, 4096, 5000, 7890, 8124, 9999]
SAMPLE_APPS = ["chrome", "notepad", "code", "spotify", "discord", "python", "node"]
SAMPLE_FOLDERS = ["Projects", "Test", "Workspace", "Backup", "Dev", "Notes", "Build", "Data"]
SAMPLE_PROGRAMS = ["python", "node", "git", "npm", "code", "java", "dotnet", "winget"]


def generate_records(limit: int = 15000) -> Generator[dict[str, Any], None, None]:
    """Generates parameterized natural-language training records."""
    db = get_command_db()
    commands = db.get_all()
    count = 0

    # 1. Generate high-density variations for priority commands
    for prefix in INTENT_PREFIXES:
        for port in SAMPLE_PORTS:
            for tmpl in QUERY_TEMPLATES["netstat"]:
                text = prefix + tmpl.format(port=port)
                yield {
                    "request": text.strip().capitalize(),
                    "command": f"netstat -ano | findstr :{port}",
                    "base_command": "netstat",
                    "category": "Networking",
                    "shell": "cmd",
                    "intent": "PORT_PROCESS_LOOKUP",
                    "parameters": {"port": port},
                    "risk_level": "LOW",
                    "requires_admin": False,
                    "destructive": False,
                }
                count += 1
                if count >= limit:
                    return

        for pid in SAMPLE_PIDS:
            for tmpl in QUERY_TEMPLATES["taskkill"][:5]:
                text = prefix + tmpl.format(pid=pid, process_name="")
                yield {
                    "request": text.strip().capitalize(),
                    "command": f"taskkill /PID {pid} /F",
                    "base_command": "taskkill",
                    "category": "Processes, Services & Tasks",
                    "shell": "cmd",
                    "intent": "PROCESS_KILL_PID",
                    "parameters": {"pid": pid},
                    "risk_level": "HIGH",
                    "requires_admin": True,
                    "destructive": True,
                }
                count += 1
                if count >= limit:
                    return

        for app in SAMPLE_APPS:
            for tmpl in QUERY_TEMPLATES["taskkill"][5:]:
                text = prefix + tmpl.format(pid=0, process_name=app)
                yield {
                    "request": text.strip().capitalize(),
                    "command": f"taskkill /IM {app}.exe /F",
                    "base_command": "taskkill",
                    "category": "Processes, Services & Tasks",
                    "shell": "cmd",
                    "intent": "PROCESS_KILL_NAME",
                    "parameters": {"process_name": f"{app}.exe"},
                    "risk_level": "HIGH",
                    "requires_admin": True,
                    "destructive": True,
                }
                count += 1
                if count >= limit:
                    return

        for host in SAMPLE_HOSTS:
            for tmpl in QUERY_TEMPLATES["ping"]:
                text = prefix + tmpl.format(host=host)
                yield {
                    "request": text.strip().capitalize(),
                    "command": f"ping -n 4 {host}",
                    "base_command": "ping",
                    "category": "Networking",
                    "shell": "cmd",
                    "intent": "NETWORK_PING",
                    "parameters": {"host": host},
                    "risk_level": "LOW",
                    "requires_admin": False,
                    "destructive": False,
                }
                count += 1
                if count >= limit:
                    return

        for name in SAMPLE_FOLDERS:
            for tmpl in QUERY_TEMPLATES["mkdir"]:
                text = prefix + tmpl.format(name=name)
                yield {
                    "request": text.strip().capitalize(),
                    "command": f'mkdir "{name}"',
                    "base_command": "mkdir",
                    "category": "File & Directory",
                    "shell": "cmd",
                    "intent": "DIRECTORY_CREATE",
                    "parameters": {"name": name},
                    "risk_level": "MEDIUM",
                    "requires_admin": False,
                    "destructive": False,
                }
                count += 1
                if count >= limit:
                    return

        for prog in SAMPLE_PROGRAMS:
            for tmpl in QUERY_TEMPLATES["where"]:
                text = prefix + tmpl.format(program=prog)
                yield {
                    "request": text.strip().capitalize(),
                    "command": f"where {prog}",
                    "base_command": "where",
                    "category": "File & Directory",
                    "shell": "cmd",
                    "intent": "EXECUTABLE_LOOKUP",
                    "parameters": {"program": prog},
                    "risk_level": "LOW",
                    "requires_admin": False,
                    "destructive": False,
                }
                count += 1
                if count >= limit:
                    return

        for tmpl in QUERY_TEMPLATES["ipconfig"]:
            for prefix in INTENT_PREFIXES:
                req = f"{prefix}{tmpl}".strip().capitalize()
                yield {
                    "request": req,
                    "command": "ipconfig",
                    "base_command": "ipconfig",
                    "category": "Networking",
                    "shell": "cmd",
                    "intent": "NETWORK_IP_LOOKUP",
                    "parameters": {},
                    "risk_level": "LOW",
                    "requires_admin": False,
                    "destructive": False,
                }
                count += 1
                if count >= limit:
                    return

        for tmpl in QUERY_TEMPLATES["tasklist"]:
            for prefix in INTENT_PREFIXES:
                req = f"{prefix}{tmpl}".strip().capitalize()
                yield {
                    "request": req,
                    "command": "tasklist",
                    "base_command": "tasklist",
                    "category": "Processes, Services & Tasks",
                    "shell": "cmd",
                    "intent": "PROCESS_LIST",
                    "parameters": {},
                    "risk_level": "LOW",
                    "requires_admin": False,
                    "destructive": False,
                }
                count += 1
                if count >= limit:
                    return

    # 2. General expansion for all 492 commands in the reference database
    for cmd in commands:
        base_intents = cmd.get("intents", []) or [f"run {cmd['clean_name']}"]
        for intent_phrase in base_intents:
            for prefix in INTENT_PREFIXES:
                req = f"{prefix}{intent_phrase}".strip().capitalize()
                yield {
                    "request": req,
                    "command": cmd["clean_name"],
                    "base_command": cmd["clean_name"],
                    "category": cmd["category"],
                    "shell": cmd["shell"],
                    "intent": f"CMD_{cmd['clean_name'].upper()}",
                    "parameters": {},
                    "risk_level": cmd["risk_level"],
                    "requires_admin": cmd["requires_admin"],
                    "destructive": cmd["destructive"],
                }
                count += 1
                if count >= limit:
                    return


def export_dataset_jsonl(output_path: Path = OUTPUT_DATASET_PATH, count: int = 15000) -> int:
    """Exports generated records to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for record in generate_records(limit=count):
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
    return written
