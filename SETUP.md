# JARVIS — First-Time Setup on a New Device

Full checklist to get the whole system running from scratch: the automation server,
built-in Gemini AI agent, and (optionally) the voice client.

## 0. Prerequisites

- **Windows 10/11**
- **Python 3.12+** installed and on PATH
- **Google Gemini API Key** — get a free API key at [Google AI Studio](https://aistudio.google.com/apikey)
- Microphone + speakers, only if you want the voice client
- *(Optional)* [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) binary on PATH if you want `ocr` actions

*(Note: Docker Desktop and n8n are no longer needed. The agent runs natively in Python via the Google GenAI SDK.)*

## 1. Get the project files

Clone or copy the `jarvis` folder to the target machine:
```powershell
cd jarvis
```

## 2. Server & AI Agent setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Create `.env` in the project root:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
JARVIS_GEMINI_MODEL=gemini-2.5-flash
```

**Run the server:**
```powershell
.venv\Scripts\python app.py
```
First run scans every installed application (Start Menu, registry, Program
Files, PATH, Store) and builds `database/apps.json` — takes a few seconds.
Windows Firewall will likely prompt the first time it binds to a port —
click **Allow** (at least for Private networks).

Confirm it's up:
```powershell
Invoke-RestMethod http://127.0.0.1:5000/
```
Should return:
```json
{
  "status": "JARVIS Desktop API Running",
  "applications_indexed": 1345,
  "agent_configured": true
}
```

Test natural language chat with JARVIS:
```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5000/chat `
  -ContentType "application/json" `
  -Body '{"message": "Jarvis, what is the system status?"}'
```

## 3. Voice client setup (optional)

Install voice dependencies:
```powershell
.venv\Scripts\pip install -r requirements-voice.txt
```

**Find and pin your microphone:**
Windows' "default" input device can sometimes be an unattached jack or phantom device. Check available devices:
```powershell
.venv\Scripts\python -m voice.list_devices
```
Add the device name or index to `.env`:
```ini
JARVIS_INPUT_DEVICE=Microphone Array
```

**Run the voice client:**
```powershell
.venv\Scripts\python -m voice.main
```
First run downloads the Whisper speech-recognition model (~150MB) and the
`hey_jarvis` wake-word model (~7MB) — both free, local, and no account needed.

**If "Hey Jarvis" doesn't trigger reliably**, run the live diagnostic to see
real mic level + wake-word confidence numbers:
```powershell
.venv\Scripts\python -m voice.diagnose
```
Tune `JARVIS_WAKE_WORD_THRESHOLD` (lower = easier to trigger) and
`JARVIS_SILENCE_RMS` (raise if ambient noise floor is high) in `.env`.

Tune the TTS voice with `GEMINI_TTS_VOICE` (e.g. `Fenrir`, `Charon`, `Kore`) and
`GEMINI_TTS_MODEL` in `.env` — see [Gemini Speech Generation docs](https://ai.google.dev/gemini-api/docs/speech-generation).

## 4. Sanity-check the whole chain

1. **Direct Action**: `POST http://127.0.0.1:5000/execute` with `{"action": "open_app", "target": "notepad"}`.
2. **AI Agent Chat**: `POST http://127.0.0.1:5000/chat` with `{"message": "Jarvis, open Notepad and write hello"}`.
3. **Voice Client**: Say "Hey Jarvis, set volume to 40 percent".
   - Wake word triggers -> records voice -> Whisper transcribes -> `agent.py` calls `set_volume` -> speaks response via Gemini TTS.

If something fails, check `logs/jarvis.log` for structured request records and timing.
