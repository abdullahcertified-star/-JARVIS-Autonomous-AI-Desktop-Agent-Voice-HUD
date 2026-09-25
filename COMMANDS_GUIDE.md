# JARVIS Windows Command Master Knowledge Base & Safe Execution Guide

This document details the command knowledge base and safe execution subsystem integrated into JARVIS, extracted from `Jarvis_Windows_Command_Master_Reference.pdf`.

---

## 1. Overview & Architecture

The command subsystem enables Jarvis to interpret freeform natural-language queries, map them to validated Windows CMD and PowerShell commands, enforce a 4-tier risk policy, and return voice-friendly natural-language responses.

```
User Request / Voice Input
         │
         ▼
 Intent Detection & Parameter Extraction (commands/intent_matcher.py)
         │
         ▼
 Command Knowledge Base (commands/database.py: SQLite + JSON, 492 commands)
         │
         ▼
 Safety & Risk Assessment (commands/safety.py: LOW / MEDIUM / HIGH / CRITICAL)
         │
    ┌────┴────────────────────────┐
    ▼                             ▼
[LOW / MEDIUM]            [HIGH / CRITICAL]
    │                             │
    │                   Confirmed by User?
    │                   ├── NO  ──► Prompts User for Confirmation (Blocked)
    │                   └── YES ──► Proceeds to Execution
    ▼                             ▼
Command Executor (commands/executor.py: CMD / PowerShell -NoProfile)
         │
         ▼
Result Interpreter (commands/interpreter.py: parses stdout/stderr into speech)
         │
         ▼
Spoken Response ("Positive sir, ...")
```

---

## 2. Command Categories (492 Cataloged Commands)

The knowledge base covers 13 master Windows families extracted directly from the reference PDF:

| Category | Command Count | Sample Commands |
| :--- | :---: | :--- |
| **File & Directory** | 43 | `cd`, `dir`, `tree`, `mkdir`, `robocopy`, `icacls`, `cipher`, `makecab` |
| **System & Information** | 28 | `ver`, `winver`, `systeminfo`, `hostname`, `whoami`, `msinfo32`, `dxdiag` |
| **Networking** | 33 | `ipconfig`, `ping`, `netstat`, `nslookup`, `route`, `Test-NetConnection` |
| **Processes, Services & Tasks** | 23 | `tasklist`, `taskkill`, `sc`, `schtasks`, `Get-Service`, `Start-Process` |
| **Users, Groups & Security** | 39 | `net user`, `net localgroup`, `whoami /all`, `cmdkey`, `Get-Acl`, `auditpol` |
| **Disk, Storage & Recovery** | 29 | `diskpart`, `chkdsk`, `defrag`, `format`, `Get-Disk`, `mountvol`, `fsutil` |
| **Windows Repair & Administration** | 36 | `sfc`, `dism`, `bootrec`, `bcdedit`, `perfmon`, `resmon`, `reg` |
| **CMD Shell & Batch Scripting** | 44 | `for`, `if`, `set`, `assoc`, `ftype`, `pushd`, `popd`, `timeout`, `redirection` |
| **PowerShell Core / Windows PowerShell** | 89 | `Get-ChildItem`, `Select-String`, `Invoke-WebRequest`, `Get-WinEvent`, etc. |
| **Developer & Git** | 49 | `git`, `python`, `pip`, `npm`, `node`, `winget`, `dotnet`, `java`, `code` |
| **Windows Package & App Management** | 20 | `winget`, `msiexec`, `Get-AppxPackage`, `DISM /Online /Get-ProvisionedAppxPackages` |
| **Diagnostics, Logs & Performance** | 26 | `eventvwr`, `wevtutil`, `resmon`, `logman`, `pktmon`, `typeperf` |
| **Windows Scripting / Legacy Utilities** | 33 | `cscript`, `wsl`, `powershell`, `pwsh`, `robocopy`, `bitsadmin`, `esentutl` |

---

## 3. Four-Tier Risk Classification & Safety Engine

Every command is validated against `commands/safety.py`:

| Risk Tier | Characteristics | Examples | Execution Behavior |
| :--- | :--- | :--- | :--- |
| **`LOW`** | Read-only queries, system metrics, non-modifying diagnostics | `ipconfig`, `ping`, `netstat`, `tasklist`, `whoami`, `hostname`, `dir`, `systeminfo` | **Executes immediately.** |
| **`MEDIUM`** | Harmless additions, package installations, folder creation, safe service restarts | `mkdir`, `New-Item`, `winget install`, `npm install`, `Restart-Service`, `copy`, `move` | **Executes immediately.** |
| **`HIGH`** | Process termination, file deletion, permission modification, firewall changes, registry edits | `taskkill`, `del`, `rd`, `Remove-Item`, `icacls`, `takeown`, `net user`, `reg delete`, `netsh advfirewall` | **REQUIRES EXPLICIT USER CONFIRMATION.** Blocked unless `confirmed=True`. |
| **`CRITICAL`** | Permanent filesystem destruction, partition wiping, boot configuration modification | `format`, `diskpart`, `Format-Volume`, `bcdedit`, `bootrec`, `reagentc`, `Initialize-Disk` | **STRICTLY BLOCKED WITHOUT HIGH-SCRUTINY CONFIRMATION.** |

### Command Injection Protection
- Multi-command chain operators (`&&`, `||`, `;`) trigger HIGH-risk confirmation gates.
- Output piping (`|`) is strictly restricted to safe filters (`findstr`, `Select-String`, `Where-Object`, `more`, `sort`, `clip`).

---

## 4. Natural Language Intent Mapping & Dynamic Parameters

The `IntentMatcher` translates human requests into validated commands:

| Natural Language Request | Detected Intent | Generated Command | Risk Tier |
| :--- | :--- | :--- | :--- |
| *"What's my IP?"* | `NETWORK_IP_LOOKUP` | `ipconfig` | `LOW` |
| *"Show detailed network configuration"* | `NETWORK_IP_DETAILED` | `ipconfig /all` | `LOW` |
| *"Flush DNS"* | `NETWORK_FLUSH_DNS` | `ipconfig /flushdns` | `LOW` |
| *"Find which process is using port 5000"* | `PORT_PROCESS_LOOKUP` | `netstat -ano \| findstr :5000` | `LOW` |
| *"Show me all running processes"* | `PROCESS_LIST` | `tasklist` | `LOW` |
| *"Create a folder called Projects on my desktop"* | `DIRECTORY_CREATE` | `mkdir "C:\Users\Abdullah_\Desktop\Projects"` | `MEDIUM` |
| *"Test internet connectivity"* | `INTERNET_CONNECTIVITY_TEST` | `ping -n 4 8.8.8.8` | `LOW` |
| *"Find Python"* | `EXECUTABLE_LOOKUP` | `where python` | `LOW` |
| *"Show network adapters"* | `NETWORK_ADAPTER_LIST` | `Get-NetAdapter` (PowerShell) | `LOW` |
| *"Show Windows services"* | `SERVICE_LIST` | `Get-Service` (PowerShell) | `LOW` |
| *"Kill process 1234"* | `PROCESS_KILL_PID` | `taskkill /PID 1234 /F` | `HIGH` (Held) |
| *"Format drive D:"* | `DISK_FORMAT` | `format D: /q` | `CRITICAL` (Held) |
| *"Disable firewall"* | `FIREWALL_DISABLE` | `netsh advfirewall set allprofiles state off` | `HIGH` (Held) |

---

## 5. Result Interpretation

CLI outputs are automatically converted into spoken natural language:

- **Port Lookups (`netstat | findstr`)**:
  - If occupied: *"Positive sir, port 5000 is being used by PID 1234 (python.exe)."*
  - If free: *"Positive sir, port 5000 is currently free and not in use by any process."*
- **IP Configuration (`ipconfig`)**:
  - *"Positive sir, your local IP address is 192.168.1.11 with default gateway 192.168.1.1."*
- **Ping / Connectivity (`ping`)**:
  - *"Positive sir, ping to 8.8.8.8 succeeded with an average latency of 14ms."*
- **Tasks (`tasklist`)**:
  - *"Positive sir, there are 184 active tasks running, including chrome.exe, code.exe, and python.exe."*

---

## 6. How to Use & Extend

### A. Via Python API
```python
from commands import IntentMatcher

matcher = IntentMatcher()

# Normal query
result = matcher.execute_request("Which process is using port 5000")
print(result["response"])
# -> "Positive sir, port 5000 is currently free and not in use by any process."

# High-risk query (requires confirmation)
blocked = matcher.execute_request("Kill process 1234", confirmed=False)
print(blocked["requires_confirmation"])  # True
print(blocked["message"])  # "This operation requires confirmation: ..."

# Once confirmed:
executed = matcher.execute_request("Kill process 1234", confirmed=True)
```

### B. Via HTTP / Dispatcher API
```bash
POST /execute
Content-Type: application/json

{
  "action": "command",
  "operation": "execute",
  "request": "what is my local IP"
}
```

### C. Adding New Commands
To add a new command or update an existing one:
1. Open [`commands/catalog.py`](file:///c:/Users/Abdullah_/Desktop/jarvis/commands/catalog.py).
2. Add an entry to `COMMAND_METADATA` with description, examples, template, and intent variations:
   ```python
   "mycommand": {
       "description": "My custom tool description.",
       "examples": ["mycommand -v"],
       "template": "mycommand {args}",
       "intents": ["run my command", "check custom status"],
   }
   ```
3. Rebuild the database:
   ```bash
   .venv\Scripts\python -c "from commands.catalog import build_and_save_catalog; build_and_save_catalog()"
   ```

### D. Updating / Retraining Dataset
To regenerate the 24,000+ training records:
```bash
.venv\Scripts\python -c "from commands.dataset_generator import export_dataset_jsonl; export_dataset_jsonl()"
```
This updates `database/jarvis_command_dataset.jsonl`.
