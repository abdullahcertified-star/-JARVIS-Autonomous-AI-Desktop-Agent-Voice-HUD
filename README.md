# JARVIS Desktop Automation Server & AI Agent

[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![AI: Google GenAI](https://img.shields.io/badge/AI-Google%20GenAI%20SDK-orange.svg)](https://ai.google.dev/)
[![Speech: Edge Neural / Gemini TTS](https://img.shields.io/badge/Voice-Edge%20Neural%20%2F%20Gemini-purple.svg)](voice/)

A local Windows desktop automation engine, voice assistant, and autonomous AI agent powered directly by the **Google GenAI SDK (`google-genai`)** with native Gemini function calling.

Commands can be spoken out loud via the floating **holographic Next.js/Three.js HUD**, queried via natural language (`POST /chat`), or triggered directly via structured JSON (`POST /execute`).

```json
{"message": "Jarvis, find which process is using port 5000"}
```
```json
{"success": true, "reply": "Positive sir, port 5000 is currently free and not in use by any process."}
```

---

## Key Features

- **No Application Lists to Maintain**: Dynamically scans the Start Menu, Desktop, Windows Registry (`App Paths` + `Uninstall`), `PATH`, `Program Files`, and Microsoft Store (UWP) apps on first run with RapidFuzz alias generation.
- **Windows Command Master Knowledge Base**: Integrates **492 reference commands** across 13 Windows administration, networking, developer, and diagnostics families.
- **4-Tier Safety & Risk Classification**: Classifies every command into **`LOW`**, **`MEDIUM`**, **`HIGH`**, or **`CRITICAL`** risk. Destructive operations (`format`, `taskkill`, `del /s`, `reg delete`, `netsh advfirewall`) are strictly gated and require explicit confirmation.
- **Interactive HUD Risk Confirmation Modal**: When a `HIGH` or `CRITICAL` risk command is triggered, an interactive glassmorphic HUD dialog appears with a live countdown timer, glowing amber/crimson safety badges, command preview, and instant Approve/Deny buttons (with dual voice/click authorization).
- **Natural Language Intent Mapping**: Converts conversational requests (*"what's my IP"*, *"find port 5000"*, *"create folder Projects on desktop"*) into validated Windows CLI and PowerShell commands with dynamic parameter binding.
- **Natural Language Result Interpretation**: Formats raw technical `stdout`/`stderr` into concise, humanized spoken responses.
- **Cinematic Marvel-Style Audio (SFX)**: Zero-latency in-memory futuristic audio cues for wake word detection, speech-end acknowledgment, action success/failure tones, standby sleep, and system shutdown.
- **Real-Time Voice Interruption (Barge-In)**: Background microphone energy monitor during TTS playback. If the user speaks while Jarvis is talking, audio cuts off within 50ms and Jarvis seamlessly returns to recording.
- **Proactive Desktop Background Watcher**: Autonomous daemon monitoring system vitals (RAM >90%, disk depletion <10GB, sustained CPU spikes, critical battery) and speaking proactive advisory alerts with intelligent cooldown debouncing.
- **Holographic 3D Voice HUD**: Floating Next.js + Three.js particle sphere reacting to wake words, voice amplitude, and listening states with continuous conversation sessions.
- **Graceful Self-Termination**: Understands natural shutdown commands (*"Jarvis terminate yourself"*, *"shutdown jarvis"*, *"goodbye"*, *"stand down"*), closing the HUD and stopping all background audio loops cleanly.
- **Rich Training Dataset**: Includes **24,110 natural-language training pairs** in `database/jarvis_command_dataset.jsonl` for offline fine-tuning or evaluation.

---

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

First run prints something like:
```text
Scanning installed applications...
Found 1345 applications in 2.9s.
  ✓ Google Chrome
  ✓ Microsoft Edge
  ✓ Microsoft Visual Studio Code (User)
  ✓ Cisco Packet Tracer
Application database loaded.
JARVIS Desktop API Ready.
```

Configure your environment in `.env` (copy from [`.env.example`](.env.example)):
```env
GEMINI_API_KEY=your_gemini_api_key_here
JARVIS_GEMINI_MODEL=gemini-flash-lite-latest
JARVIS_HOST=0.0.0.0
JARVIS_PORT=5000
```

---

## Windows Command Knowledge Base & Safety Layer

JARVIS embeds an internal command knowledge base covering 13 master Windows categories:

| Category | Commands | Common Uses |
| :--- | :---: | :--- |
| **File & Directory** | 43 | `dir`, `tree`, `mkdir`, `robocopy`, `icacls`, `cipher`, `makecab` |
| **System & Information** | 28 | `ver`, `winver`, `systeminfo`, `hostname`, `whoami`, `msinfo32` |
| **Networking** | 33 | `ipconfig`, `ping`, `netstat`, `nslookup`, `route`, `Test-NetConnection` |
| **Processes, Services & Tasks** | 23 | `tasklist`, `taskkill`, `sc`, `schtasks`, `Get-Service`, `Start-Process` |
| **Users, Groups & Security** | 39 | `net user`, `net localgroup`, `whoami /all`, `cmdkey`, `Get-Acl`, `auditpol` |
| **Disk, Storage & Recovery** | 29 | `diskpart`, `chkdsk`, `defrag`, `format`, `Get-Disk`, `mountvol` |
| **Windows Repair & Administration** | 36 | `sfc`, `dism`, `bootrec`, `bcdedit`, `perfmon`, `resmon`, `reg` |
| **CMD Shell & Batch Scripting** | 44 | `for`, `if`, `set`, `assoc`, `ftype`, `pushd`, `popd`, `redirection` |
| **PowerShell Core / Windows PowerShell** | 89 | `Get-ChildItem`, `Select-String`, `Invoke-WebRequest`, `Get-WinEvent` |
| **Developer & Git** | 49 | `git`, `python`, `pip`, `npm`, `node`, `winget`, `dotnet`, `java` |
| **Windows Package & App Management** | 20 | `winget`, `msiexec`, `Get-AppxPackage`, `DISM /Get-ProvisionedAppxPackages` |
| **Diagnostics, Logs & Performance** | 26 | `eventvwr`, `wevtutil`, `resmon`, `logman`, `pktmon`, `typeperf` |
| **Windows Scripting / Legacy Utilities** | 33 | `cscript`, `wsl`, `powershell`, `pwsh`, `robocopy`, `bitsadmin` |

### Safety Risk Policy

```
User Request ──► Intent Matcher ──► Safety Engine ──► [Risk Check]
                                                           │
              ┌────────────────────────────────────────────┴───────────────────────────┐
              ▼                                                                        ▼
       [LOW / MEDIUM]                                                           [HIGH / CRITICAL]
       Auto-executed                                                            Confirmation Required
       • ipconfig, ping, tasklist                                               • taskkill, del /s, rd /s
       • dir, systeminfo, whoami                                                • format, diskpart, bcdedit
       • mkdir, winget install                                                  • reg delete, netsh advfirewall
```

For full details, see [`COMMANDS_GUIDE.md`](COMMANDS_GUIDE.md).

---

## API Reference

### Endpoints
- `POST /chat`: Multi-turn conversational interaction with JARVIS (supports automatic function calling). Body: `{"message": "string"}`.
- `POST /chat/reset`: Clears conversation history.
- `POST /execute`: Direct low-level JSON action dispatcher.
- `GET /`: Health status and count of indexed applications.
- `GET /dashboard`: Web telemetry dashboard.

### Core Dispatcher Actions

| Action | Required Fields | Description |
| :--- | :--- | :--- |
| `command` | `operation` (`execute` / `match` / `search` / `info`) | Natural-language Windows command executor, intent matcher, and knowledge base search. |
| `open_app` | `target` (aliases: `app`, `app_name`) | Fuzzy-matches and launches any installed desktop or Store application. |
| `refresh_apps` | — | Rescans the system and updates `database/apps.json`. |
| `open_url` | `url` (+optional `browser`) | Opens a web page in default or specified browser. |
| `search_google` | `query` (+optional `browser`) | Performs a Google search. |
| `search_youtube` | `query` (+optional `browser`) | Searches YouTube. |
| `get_news` | optional `topic`, `limit` | Fetches live Google News RSS headlines. |
| `keyboard` | `operation`: `type` / `press` / `hotkey` | Keystroke and text typing automation. |
| `mouse` | `operation`: `move` / `click` / `scroll` / `position` | Cursor movement and clicks. |
| `clipboard` | `operation`: `copy` / `paste` / `clear` | Windows clipboard management. |
| `explorer` | `operation`: `open` / `reveal` / `read` / `create` / `update` / `delete` | File/folder CRUD. Deletions safely route to Recycle Bin via `send2trash`. |
| `system` | `operation`: `status` / `volume_up` / `volume_down` / `set_volume` / `mute` / `run_command` / `shutdown` / `restart` / `lock` / `sleep` | Controls system hardware, audio, power states, and executes validated shell commands. |
| `media` | `operation`: `play_pause` / `next` / `previous` / `mute` | Standard media playback virtual keys. |
| `screenshot` | `operation`: `capture` (+optional `region`) | Captures and saves desktop screenshots to `screenshots/`. |
| `ocr` | `operation`: `read_screen` / `read_region` | Optical character recognition (requires Tesseract). |

---

## Holographic Voice HUD

JARVIS includes a floating desktop HUD featuring a Next.js/Three.js interactive particle sphere.

### Running the Voice Client
```powershell
.venv\Scripts\pip install -r requirements-voice.txt
.venv\Scripts\python -m voice.main
```

### Voice Interaction Features
- **Wake Word**: Offline detection of *"Hey Jarvis"* via `openWakeWord`.
- **Speech Recognition**: Local Whisper transcription (`faster-whisper`) with automated speech-to-text phonetic repair.
- **Speech Synthesis**: Ultra-natural Edge Neural TTS / Gemini TTS with natural humanized punctuation pauses.
- **Real-Time Voice Barge-In**: Background microphone monitor during playback; speaking immediately cuts off audio playback within 50ms and transitions directly to recording.
- **Continuous Conversation**: Stays awake for 45 seconds after wake-up so you don't have to repeat *"Hey Jarvis"* for follow-up queries.
- **Voice Control & Standby**:
  - Say *"go to sleep"*, *"stand by"*, *"dismissed"*, or *"goodbye"* to enter standby mode.
  - Say *"Jarvis terminate yourself"*, *"shutdown jarvis"*, or *"exit"* to close the application and stop all background processes cleanly.


### Bilingual Auto-Switch & Humanized Urdu Voice (English & Urdu / Roman Urdu / Hinglish)
- **Seamless Multilingual Listening**: Multilingual Whisper (`faster-whisper`) automatically transcribes and understands English, Urdu Nastaliq, Roman Urdu, and Hinglish with zero manual language switching.
- **Dynamic Dual-Engine Speech Synthesis**: Intelligently auto-switches TTS voices in real-time:
  - **English**: Deep cinematic tone via `en-US-ChristopherNeural` (`-4Hz`, `-2%`).
  - **Humanized Urdu**: Cultured, warm, non-robotic delivery via `ur-PK-AsadNeural` (`-2Hz`, `-4%`).
- **Ultra-Human Urdu Vocal Delivery (Non-Robotic)**:
  - **Acoustic Breath Pauses**: Converts commas and clause transitions into acoustic breathing pauses (`... `), giving the neural model natural vocal decay and conversational cadence instead of flat, monotone rush.
  - **Native Script Phoneme Shaping**: Transparently maps Roman Urdu and conversational words to native Nastaliq script before synthesis for authentic, native Pakistani Urdu pronunciation.
  - **Warm Conversational Pitch**: Tuned to `-2Hz` pitch and `-4%` tempo to remove metallic synthesizer resonance and provide a rich, relaxed butler cadence.
- **Conversational Language Mirroring**: Speaks to Sir Abdullah in whichever language he addresses the assistant in:
  - English: *"Positive sir, Google Chrome has been launched."*
  - Urdu / Roman Urdu: *"جی سر عبداللہ... والیم بڑھا دیا ہے۔ فرمائیے، مزید کیا خدمت کروں؟"*
- **0ms Bilingual Fast-Paths**: Instant zero-latency responses for Urdu greetings (*"kya haal hai"*, *"kaise ho"*), time/date (*"kya time hai"*, *"aaj kya tareekh hai"*), volume controls (*"awaz barhao"*, *"awaz kam karo"*, *"awaz band karo"*), and maintenance (*"recycle bin saaf karo"*).
- **Clean Zero-Beep Audio**: Silent, professional voice UX without distracting speech-start or speech-end beeps.

### Multimodal Screen Perception & Vision QA (Gemini VLM)
- **Visual Desktop QA**: Ask *"Jarvis, what is on my screen?"*, *"Describe my screen"*, or *"What do you see?"* for an instant, natural summary of active windows and visual content.
- **Smart Error Debugger**: Ask *"Jarvis, explain this error"* — JARVIS scans the screen for error dialogs, red terminal stack traces, or exception popups, identifies the root cause, and provides a direct fix.
- **Pure-Software Text Extraction**: Transcribe readable text directly from the screen via Gemini Vision without requiring local Tesseract binaries.
- **Ultra-Fast Path**: Regex triggers bypass conversational LLM overhead, capturing and analyzing the screen immediately.

### Multi-Step Macro Orchestrator & Workflow Automation
- **Built-in Workflows**:
  - `dev_workspace`: *"Jarvis, prepare dev workspace"* launches VS Code, Terminal, GitHub, and sets audio volume to 30%.
  - `goodnight_routine`: *"Goodnight routine"* pauses media playback, sets volume to 0%, minimizes all windows, and dims screen brightness.
  - `meeting_mode`: *"Meeting mode"* silences background media, adjusts conversational volume, and cleans up window clutter.
  - `gaming_mode`: *"Gaming mode"* maximizes display brightness and boosts gaming audio.
  - `morning_briefing`: *"Morning routine"* sets volume, reads top technology news, and reports battery/network status.
- **Custom User Macros**: Create, save, and delete custom chained desktop sequences saved persistently in `database/workflows.json`.

### Ambient Context, Focus / DND & Quiet Hours
- **Focus & Do-Not-Disturb Mode**: Say *"Jarvis, enter focus mode on machine learning"* to activate focus tracking and silence non-critical background notifications. Ask *"How long have I been focusing?"* for live session duration reports.
- **Intelligent Alert Suppression**: Proactive background alerts (RAM/disk warnings) are automatically suppressed during active focus sessions and quiet hours, while critical safety alerts (e.g. low battery reserve) always break through.
- **Windows User Presence & Idle Detection**: Queries native `GetLastInputInfo` (0ms overhead) to classify state as *active* (<1 min), *idle* (1–5 min), or *away* (>5 min).
- **Quiet Hours**: Automatically enforces nighttime quiet periods (default: 23:00 to 07:00) with configurable start/end hours.

---

## Architecture

```text
app.py                  Flask HTTP API (/chat, /execute, /dashboard)
agent.py                Gemini AI Agent with function calling & 0ms fast-paths
dispatcher.py           Central router, request validator, and latency logger
config.py               Configuration, paths, environment variables
actions/                Action domain handlers (context, macro, vision, command, apps, etc.)
commands/               Windows Command Master reference knowledge base & safety engine
  catalog.py            PDF extractor and catalog compiler (492 commands)
  database.py           SQLite (commands.db) & JSON (commands.json) store with fuzzy search
  safety.py             4-tier risk classification, injection protection, confirmation policy
  executor.py           Safe CMD and PowerShell subprocess runner with timeouts
  interpreter.py        Translates CLI stdout/stderr into voice-friendly natural language
  intent_matcher.py     Natural-language intent detector and dynamic parameter parser
  dataset_generator.py  Generates 24,000+ training records (jarvis_command_dataset.jsonl)
scanner/                Windows filesystem, Start Menu, Registry, and Store app scanner
search/                 RapidFuzz indexing over installed applications
voice/                  Voice client: wake word listener, Whisper STT, TTS, and pywebview HUD
  web/                  Next.js 15 + Three.js holographic particle orb application
tests/                  Pytest suite (159 automated unit and integration tests)
```

---

## Automated Tests

Run the full automated test suite (including command database, safety blocks, agent tools, vision QA, macro orchestrator, ambient context, bilingual auto-switch, and API routes):

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests/ -v
```

```text
======================= 159 passed, 1 warning in 23.12s =======================
```

---

## License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)** — see the [LICENSE](LICENSE) file for details.
Copyright (C) 2026 Abdullah.
