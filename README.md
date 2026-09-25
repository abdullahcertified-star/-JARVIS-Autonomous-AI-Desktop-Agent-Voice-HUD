# JARVIS Desktop Automation Server & AI Agent

A local Windows desktop automation engine and AI assistant powered directly by
the **Google GenAI SDK (`google-genai`)** with native Gemini function calling.
Commands can be sent via natural language (voice or `POST /chat`) or directly via
structured JSON (`POST /execute`). The agent executes native desktop actions
in-process through a fixed, validated set of actions (see **Security** below).

```json
{"message": "Jarvis, open Chrome and search for quantum computing"}
```

```json
{"success": true, "reply": "Searching Google for quantum computing in Google Chrome, sir."}
```

## Why no app list to maintain

There is no hardcoded map of app names to paths anywhere in this project.
On first run (or whenever `database/apps.json` is missing), the server scans
the machine — Start Menu, Desktop, the Windows Registry (App Paths +
Uninstall keys), Program Files, `PATH`, and Microsoft Store/UWP packages —
merges what it finds, generates search aliases automatically, and caches the
result. Install Discord tomorrow, restart JARVIS, and it's just there.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

First run prints something like:

```
Scanning installed applications...
Found 1345 applications in 2.9s.
  ✓ Google Chrome
  ✓ Microsoft Edge
  ✓ Microsoft Visual Studio Code (User)
  ✓ Cisco Packet Tracer
Application database loaded.
JARVIS Desktop API Ready.
```

Later runs load `database/apps.json` from cache instead of rescanning. Force
a rescan (e.g. after installing new software) with the `refresh_apps`
action, or by deleting `database/apps.json`.

Config (host/port/debug/search sensitivity) lives in `config.py`, overridable
via `.env` — see the `JARVIS_*` variables there.

Optional: OCR requires the [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
binary on `PATH` (not pip-installable). Without it, `ocr` actions return a
clear error instead of failing silently.

## Security

There is no authentication in front of `/execute`, and its capabilities
include arbitrary shell command execution (`system.run_command`), reading
and writing any file the OS account can reach (`explorer.read`/`create`/
`update`), and full power control (`system.shutdown`/`restart`). This is a
deliberate design choice matching the trust model of the whole project: it
executes because *you* (or your AI agent) told it to, the same as running a
command in your own terminal.

That only holds as long as nothing untrusted can reach port `5000`:
- Don't bind `JARVIS_HOST` to a public interface or forward the port through
  your router.
- Keep it to `127.0.0.1`/Docker's internal network (`host.docker.internal`)
  unless you have a real reason and a real auth layer in front of it.
- Treat anything with network access to this port as having full control of
  the machine, because it does.

`explorer.delete` goes through the Recycle Bin (not a permanent unlink), so
an accidental or bad AI-driven delete is recoverable the same way an
accidental Explorer delete is — that's the one safety net built in. Nothing
else here has a confirmation step; the AI is expected to get the request
right the first time, same as you would.

## API

Endpoints:
- `POST /chat`: Natural-language interaction with the JARVIS Gemini Agent (Automatic Function Calling). Body: `{"message": "string"}`.
- `POST /chat/reset`: Clears the agent's multi-turn conversation memory.
- `POST /execute`: Direct low-level structured JSON execution endpoint.
- `GET /`: Health check reporting server status and application index count.

Every response is `{"success": bool, "message": str, ...extra fields}`. The
HTTP status is `200` for any request the server understood and processed
(including a business-logic failure like "app not found" — check `success`),
and `400` only when the body wasn't valid JSON or missed required parameters.

### Actions

| action | fields | notes |
|---|---|---|
| `open_app` | `target` (aliases: `app`, `app_name`) | Fuzzy-matched against the app database. |
| `refresh_apps` | — | Rescans the machine and rebuilds the database. |
| `open_url` | `url` (+optional `browser`) | |
| `search_google` | `query` (+optional `browser`) | |
| `search_youtube` | `query` (+optional `browser`) | |
| `get_news` | optional `topic`, `limit` | Google News RSS feed items. |
| `keyboard` | `operation`: `type` (+`text`) / `press` (+`key`) / `hotkey` (+`keys`: list) | |
| `mouse` | `operation`: `move`/`click`/`double_click` (+`x`,`y`,`button`) / `drag` (+`x1`,`y1`,`x2`,`y2`) / `scroll` (+`amount`) / `position` | |
| `clipboard` | `operation`: `copy` (+`text`) / `paste` / `clear` | |
| `explorer` | `operation`: `open` / `reveal` (+`path`) / `read` (+`path`) / `create` (+`path`, `content`, `is_folder`) / `update` (+`path`, `content`, `append`) / `delete` (+`path`) | File CRUD. `read` lists a directory or returns file text (capped, see `truncated`). `delete` goes to the Recycle Bin, not permanent. `create` fails if the path already exists; `update` fails if it doesn't. |
| `system` | `operation`: `shutdown`/`restart`/`lock`/`sleep`/`volume_up`/`volume_down`/`mute`/`set_volume` (+`level`: 0-100)/`status`/`run_command` (+`command`, optional `cwd`, `timeout`) | `run_command` executes via a shell subprocess and returns `stdout`/`stderr`/`exit_code` -- `success` reflects the command's own exit code, not just whether it ran. |
| `media` | `operation`: `play_pause`/`next`/`previous`/`volume_up`/`volume_down`/`mute` | |
| `screenshot` | `operation`: `capture` (+optional `region`: `[x,y,w,h]`) | Saved under `screenshots/`. |
| `ocr` | `operation`: `read_screen` / `read_region` (+`region` for the latter) | Requires Tesseract. |

Unknown actions/operations and missing required fields return
`{"success": false, "message": "..."}` with a specific explanation.

`browser` on the three URL-opening actions is optional and fuzzy-matched
the same way `open_app`'s `target` is (e.g. `"edge"`, `"chrome"`, `"firefox"`)
-- omit it to use the OS default browser instead.

## Architecture

```
app.py               Flask app factory, startup banner, /chat, /execute, and / routes
agent.py             Autonomous Gemini Agent (google-genai) with in-process tool calling
dispatcher.py        action-name -> handler registry, validation, logging, timing
config.py            paths, host/port/debug, Gemini keys/models, search sensitivity
database/apps.json   generated app database (gitignored, regenerated on demand)
scanner/             one module per discovery source + app_scanner.py orchestrator
search/              RapidFuzz-backed AppIndex over the app database
actions/             one module per action domain, handlers self-register with @dispatcher.register
utils/               logger, request validator, path resolution, small shared helpers
logs/jarvis.log      one structured line per request: action, target, success, duration
voice/               local voice client: wake-word, whisper STT, agent bridge, neural TTS, GUI
tests/               pytest: unit tests for search, agent, actions, and Flask API
```

Adding a new action means adding one function to an `actions/*.py` module
decorated with `@register("your_action")`, an entry in
`utils/validator.py`'s `ACTION_SCHEMAS`, and exposing the Python tool in
`agent.py` — `app.py` and `dispatcher.py` never need to change.

## AI Agent & Natural Language Chat

JARVIS features a built-in agent powered by the **Google GenAI SDK (`google-genai`)**.
No external orchestrator or Docker containers are required.

To chat with JARVIS via HTTP:
```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5000/chat `
  -ContentType "application/json" `
  -Body '{"message": "Jarvis, what is the system status?"}'
```

The agent automatically selects and executes the appropriate desktop tools,
maintains conversation history, and responds with the JARVIS persona.

## Tests

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests/ -v
```

`test_search.py` runs against an in-memory fixture.
`test_agent.py` tests agent tool mappings, result formatting, and the `/chat` route.
`test_api.py` drives the Flask app and exercises reversible actions.

## Voice client

`voice/` is a separate, standalone voice interface that connects directly to the
in-process JARVIS Gemini agent. It listens for the wake word "Hey Jarvis"
(via `openWakeWord` — free, fully offline, no account needed), records until
you stop talking, transcribes with Whisper (via `faster-whisper`, runs locally),
sends the text to `agent.py`, and speaks the reply out loud using Gemini Neural TTS.

Setup:
```powershell
.venv\Scripts\pip install -r requirements-voice.txt
```
Ensure `GEMINI_API_KEY` is present in `.env`.

Run it:
```powershell
.venv\Scripts\python -m voice.main
```

Say "Hey Jarvis", then your request. Tuning knobs (silence detection, model size,
TTS voice/rate) are in `voice/config.py`, all overridable via `.env`.

## License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)** — see the [LICENSE](LICENSE) file for full details.
