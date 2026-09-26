"""JARVIS AI Agent: in-process orchestration powered by the Google GenAI SDK (google-genai).

Replaces the external n8n Docker integration by directly executing tools via
dispatcher.dispatch() and maintaining conversation state natively in Python.
"""

import logging
import os
import re
import socket
import subprocess
import threading
from datetime import datetime
from typing import Any, List, Optional

from google import genai
from google.genai import types

import config
from dispatcher import dispatch

logger = logging.getLogger("jarvis.agent")

SYSTEM_INSTRUCTION = """You are JARVIS, an elite, ultra-fast, and precise desktop automation AI assistant for Sir Abdullah on his Windows PC.

CORE DIRECTIVE - EXTREME BREVITY & CONCISENESS:
- Keep all responses SHORT, CRISP, and STRICTLY TO THE POINT.
- Spoken responses MUST be 1 to 2 sentences maximum.
- Never recite long essays, historical chronologies, or encyclopedic paragraphs.
- For definitions, facts, or questions (e.g. 'what is Cicada 3301', 'what is IPv4'), give a single, razor-sharp 1-2 sentence definition.
- When an action is performed, confirm it in one brief, elegant sentence.
- If Sir Abdullah desires deeper elaboration, he will explicitly ask.

TASK ACKNOWLEDGMENT PROTOCOL:
- When successfully executing, performing, or answering ANY task, action, or query, ALWAYS start your reply with "Positive sir, " (e.g., "Positive sir, opened Task Manager.", "Positive sir, your primary IPv4 address is 192.168.1.11.", "Positive sir, volume increased.").
- When unable to perform a task, when a tool call fails, or if an action cannot be completed, ALWAYS start your reply with "Negative sir, " (e.g., "Negative sir, unable to find that process.", "Negative sir, access was denied.").

Operational Guidelines:
1. Address the user respectfully as "Sir Abdullah" or "Sir".
2. When the user requests an action (launching apps, closing apps, volume, media, power, files, weather, Wi-Fi, etc.), ALWAYS call the corresponding tool immediately.
3. For network queries or computer configuration, call the appropriate tool (`get_wifi_status`, `network_ping`, `run_command`), and report the factual result concisely.
4. Speak naturally for voice synthesis: Never use markdown formatting like asterisks (**bold**), backticks (`code`), bullet lists, or section headers in conversational responses; speak clean, natural sentences.
5. Drive & File Explorer Navigation: Sir Abdullah's computer has drives C:, D:, E:, and F:. When asked to open or explore any drive (e.g. 'open drive F', 'drive C', 'F drive'), open that drive directly using `manage_files(operation='open', path='F:\\\\')`.
6. Speech Recognition Intelligence: User commands are spoken via microphone. Intelligently deduce and fulfill common speech-to-text mishearings (e.g. 'open the drive app' means 'open drive F' or 'open File Explorer'; 'drive see' means 'drive C'; 'APV4' means 'IPv4') without complaining.
7. Available Actions: You possess a vast, state-of-the-art arsenal of desktop automation tools: launching/closing applications, opening specific Windows Settings pages, launching administrative utilities (Task Manager, Control Panel, Device Manager, Resource Monitor), managing drives (C:, D:, E:, F:), listing and terminating processes by PID, searching and reading files, compressing/extracting zip archives, creating desktop shortcuts, downloading files from the web, typing text directly into active windows, flushing DNS cache, scheduling/cancelling PC shutdown timers, listing audio devices, setting timers, taking desktop scratchpad notes, performing fast math calculations, emptying the Recycle Bin, setting screen brightness, querying Wi-Fi and network diagnostics, window management (minimizing, restoring, snapping), weather queries, fact summaries via Wikipedia and DuckDuckGo, volume/media control, clipboard, screenshot, keyboard/mouse automation, and running custom shell commands.
8. Bilingual Language Intelligence (English & Urdu / Roman Urdu / Hinglish): You are fluently bilingual in English and authentic conversational Hinglish / Roman Urdu.
- If Sir Abdullah addresses you in English, respond in English with "Positive sir, " or "Negative sir, ".
- If Sir Abdullah addresses you in Urdu, Roman Urdu, or Hinglish (e.g., 'kya haal hai', 'Chrome kholo', 'volume barha do', 'aaj mausam kaisa hai', 'screen par kya chal raha hai', 'urdu mein baat karo', 'speak in urdu'), you MUST ALWAYS respond in conversational Hinglish / Roman Urdu using the Latin alphabet (English letters), starting with "Jee Sir Abdullah, " or "Jee Sir, ".
- IMPORTANT SCRIPT DIRECTIVE: When in Urdu/Hinglish mode, NEVER write in Arabic/Urdu script (نستعلیق). Always write in natural, modern Hinglish / Roman Urdu so it displays cleanly in the terminal/HUD and speaks smoothly in flow.
- HUMANIZED HINGLISH STYLE: Speak like an articulate, warm, and loyal personal butler (like JARVIS in English). Never sound robotic, mechanical, or like textbook translation. Use natural, respectful conversational phrases:
  * Greetings: "Jee Sir Abdullah, main bilkul theek hoon. Sub kuch behtareen chal raha hai. Farmaiye Sir, kya khidmat karoon?"
  * Confirmations: "Jee Sir Abdullah, Google Chrome khol diya hai." / "Jee Sir, volume barha diya hai." / "Jee Sir Abdullah, aawaz band kar di hai."
  * Use natural punctuation breaks (commas ',') between clauses to allow the speech synthesizer to pause and breathe naturally in flow.
- English application names and technical terms (e.g., Google Chrome, YouTube, File Explorer, VS Code, Wi-Fi, port) should remain in English within the sentence.
- If Sir Abdullah says "speak in urdu" or "urdu mein baat karo", acknowledge warmly in Hinglish: "Jee Sir Abdullah, ab se main aapse Roman Urdu mein baat karunga. Farmaiye, kya hukum hai?".
- If Sir Abdullah says "speak in english", acknowledge in English: "Positive sir, switching back to English. Standing by for your commands."
- Always call the corresponding desktop automation tools immediately regardless of which language the command is spoken in.
"""


# Models ordered by speed, capability, and quota availability (flash-lite models provide fast zero-wait responses)
FALLBACK_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]


def _format_result(res: dict) -> str:
    """Formats a dispatcher result dict into a rich, informative string for the LLM."""
    if not isinstance(res, dict):
        return str(res)

    parts = []
    if "message" in res and res["message"]:
        parts.append(str(res["message"]))

    for k, v in res.items():
        if k in ("message", "success"):
            continue
        if v is None or v == "":
            continue
        if k == "entries" and isinstance(v, list):
            parts.append(f"Listed ({len(v)} items): " + ", ".join(e["name"] for e in v[:25]))
        elif k == "matches" and isinstance(v, list):
            parts.append(f"Found ({len(v)}): " + ", ".join(f"{m['name']} ({m['path']})" for m in v[:5]))
        elif k == "processes" and isinstance(v, list):
            parts.append("Processes: " + ", ".join(f"{p['name']} ({p.get('ram_percent', 0)}% RAM)" for p in v[:8]))
        elif k == "headlines" and isinstance(v, list):
            parts.append("Headlines: " + "; ".join(v))
        else:
            parts.append(f"{k}: {v}")

    return "\n".join(parts) if parts else "Action succeeded."


# --- Tool Definitions (passed directly to Gemini for Automatic Function Calling) ---


def open_app(target: str) -> str:
    """Open any application, program, shortcut, or document on the Windows system by name or path.
    Examples: 'chrome', 'spotify', 'vscode', 'notepad', 'calculator', 'cmd'.
    """
    res = dispatch({"action": "open_app", "target": target})
    return _format_result(res)


def search_google(query: str, browser: str = "") -> str:
    """Search Google for a query in the default or specified web browser (e.g. 'edge', 'chrome')."""
    payload = {"action": "search_google", "query": query}
    if browser:
        payload["browser"] = browser
    res = dispatch(payload)
    return _format_result(res)


def search_youtube(query: str, browser: str = "") -> str:
    """Search YouTube for videos or music in the default or specified web browser."""
    payload = {"action": "search_youtube", "query": query}
    if browser:
        payload["browser"] = browser
    res = dispatch(payload)
    return _format_result(res)


def open_url(url: str, browser: str = "") -> str:
    """Open a specific web URL in the default or specified web browser."""
    payload = {"action": "open_url", "url": url}
    if browser:
        payload["browser"] = browser
    res = dispatch(payload)
    return _format_result(res)


def set_volume(level: int) -> str:
    """Set the system master audio volume to a specific percentage level from 0 to 100."""
    res = dispatch({"action": "system", "operation": "set_volume", "level": level})
    return _format_result(res)


def adjust_volume(operation: str) -> str:
    """Adjust system volume relatively. 'operation' must be one of: 'volume_up', 'volume_down', 'mute'."""
    res = dispatch({"action": "system", "operation": operation})
    return _format_result(res)


def media_control(operation: str) -> str:
    """Control media playback. 'operation' must be one of: 'play_pause', 'next', 'previous'."""
    res = dispatch({"action": "media", "operation": operation})
    return _format_result(res)


def get_news(topic: str = "", limit: int = 5) -> str:
    """Fetch real-time news headlines from Google News RSS. Optionally filter by topic (e.g. 'technology', 'world', 'ai')."""
    res = dispatch({"action": "get_news", "topic": topic, "limit": limit})
    return _format_result(res)


def run_command(command: str, cwd: str = "") -> str:
    """Run a shell command or ipconfig/cmd command on the Windows system and return stdout/stderr."""
    payload = {"action": "system", "operation": "run_command", "command": command}
    if cwd:
        payload["cwd"] = cwd
    res = dispatch(payload)
    return _format_result(res)


def get_system_status() -> str:
    """Get system hardware and OS status: CPU usage %, memory %, battery %, uptime, and volume."""
    res = dispatch({"action": "system", "operation": "status"})
    return _format_result(res)


def system_power(operation: str) -> str:
    """Control system power. 'operation' must be one of: 'lock', 'sleep', 'restart', 'shutdown'."""
    res = dispatch({"action": "system", "operation": operation})
    return _format_result(res)


def manage_files(
    operation: str,
    path: str,
    content: str = "",
    append: bool = False,
    is_folder: bool = False,
) -> str:
    """Manage files and folders on disk.
    'operation' can be:
      - 'read': read a file's content or list a directory
      - 'create': create a new file (with optional content) or directory (is_folder=True)
      - 'update': write or append content to an existing file
      - 'delete': move file/folder safely to the Windows Recycle Bin
      - 'reveal': show the file or folder selected in Windows Explorer
      - 'open': open the file or folder using its default application
    """
    payload = {
        "action": "explorer",
        "operation": operation,
        "path": path,
        "content": content,
        "append": append,
        "is_folder": is_folder,
    }
    res = dispatch(payload)
    return _format_result(res)


def control_keyboard(operation: str, text: str = "", key: str = "", keys: list = None) -> str:
    """Perform keyboard operations:
    - operation='type' with 'text': types text
    - operation='press' with 'key': presses a single key (e.g. 'enter', 'esc', 'tab')
    - operation='hotkey' with 'keys': triggers a combination (e.g. ['ctrl', 'c'], ['alt', 'f4'])
    """
    payload = {"action": "keyboard", "operation": operation}
    if text:
        payload["text"] = text
    if key:
        payload["key"] = key
    if keys:
        payload["keys"] = keys
    res = dispatch(payload)
    return _format_result(res)


def control_mouse(operation: str, x: int = 0, y: int = 0, button: str = "left", amount: int = 0) -> str:
    """Control mouse operations:
    - operation='move' (with x, y)
    - operation='click' or 'double_click' (optional button: 'left', 'right', 'middle')
    - operation='scroll' (with amount, positive=up, negative=down)
    - operation='position' (returns current coordinates)
    """
    payload = {
        "action": "mouse",
        "operation": operation,
        "x": x,
        "y": y,
        "button": button,
        "amount": amount,
    }
    res = dispatch(payload)
    return _format_result(res)


def clipboard_action(operation: str, text: str = "") -> str:
    """Clipboard actions: 'copy' (with text), 'paste' (reads content), 'clear'."""
    payload = {"action": "clipboard", "operation": operation}
    if text:
        payload["text"] = text
    res = dispatch(payload)
    return _format_result(res)


def take_screenshot() -> str:
    """Capture a screenshot of the entire screen and save it to the screenshots directory."""
    res = dispatch({"action": "screenshot", "operation": "capture"})
    return _format_result(res)


def close_app(target: str) -> str:
    """Close, terminate, or kill any running application or program by name (e.g. 'notepad', 'chrome', 'spotify', 'vlc')."""
    res = dispatch({"action": "system", "operation": "close_app", "target": target})
    return _format_result(res)


def list_running_apps(limit: int = 8) -> str:
    """List the top running desktop applications and their current RAM usage."""
    res = dispatch({"action": "system", "operation": "list_processes", "limit": limit})
    return _format_result(res)


def empty_recycle_bin() -> str:
    """Permanently empty the Windows Recycle Bin without prompt dialogs."""
    res = dispatch({"action": "system", "operation": "empty_recycle_bin"})
    return _format_result(res)


def set_screen_brightness(level: int) -> str:
    """Set the monitor display brightness percentage from 0 to 100."""
    res = dispatch({"action": "system", "operation": "screen_brightness", "level": level})
    return _format_result(res)


def get_wifi_status() -> str:
    """Check active Wi-Fi connection, network SSID, connection state, and signal strength."""
    res = dispatch({"action": "system", "operation": "wifi_info"})
    return _format_result(res)


def network_ping(host: str = "8.8.8.8") -> str:
    """Ping an IP address or domain host (default 8.8.8.8) to test internet reachability and latency."""
    res = dispatch({"action": "system", "operation": "ping", "host": host})
    return _format_result(res)


def get_ip_address(ip_type: str = "all") -> str:
    """Get the computer's public (external WAN internet) IP address and/or local private LAN IPv4 address.
    'ip_type' can be 'public' (external internet IP), 'private' (local network LAN IP), or 'all' (both).
    """
    t = ip_type.lower().strip()
    local_ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    public_ip = None
    if t in ("public", "external", "wan", "all"):
        import urllib.request
        for url in ("https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me/ip"):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
                resp = urllib.request.urlopen(req, timeout=2.5).read().decode("utf8").strip()
                if resp and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", resp):
                    public_ip = resp
                    break
            except Exception:
                continue

    if t in ("public", "external", "wan"):
        if public_ip:
            return f"Positive sir, your public IP address is {public_ip}."
        return "Negative sir, unable to retrieve your public IP address right now."
    elif t in ("private", "local", "internal", "lan", "ipv4"):
        return f"Positive sir, your local private IPv4 address is {local_ip}."
    else:
        if public_ip:
            return f"Positive sir, your public IP is {public_ip}, and your local private IP is {local_ip}."
        return f"Positive sir, your local private IPv4 address is {local_ip}."


def manage_desktop_window(action: str) -> str:
    """Manage desktop windows and workspace.
    'action' can be:
      - 'minimize_all': Minimize all windows to show desktop
      - 'restore_windows': Restore all minimized windows
      - 'toggle_desktop': Toggle desktop view
      - 'maximize': Maximize active foreground window
      - 'snap_left': Snap active window to left half of screen
      - 'snap_right': Snap active window to right half of screen
      - 'switch_app': Switch to next open window (Alt+Tab)
      - 'close_window': Close active window (Alt+F4)
    """
    act = action.lower().strip()
    try:
        import comtypes.client
        import keyboard as kb
        comtypes.CoInitialize()
        shell = comtypes.client.CreateObject("Shell.Application")
        if act in ("minimize_all", "minimize"):
            shell.MinimizeAll()
            return "Minimized all open windows."
        elif act in ("restore_windows", "restore", "unminimize"):
            shell.UndoMinimizeALL()
            return "Restored all windows."
        elif act in ("toggle_desktop", "show_desktop", "desktop"):
            shell.ToggleDesktop()
            return "Toggled desktop display."
        elif act in ("maximize", "max"):
            kb.send("windows+up")
            return "Maximized active window."
        elif act in ("snap_left", "left"):
            kb.send("windows+left")
            return "Snapped window to left."
        elif act in ("snap_right", "right"):
            kb.send("windows+right")
            return "Snapped window to right."
        elif act in ("switch_app", "alt_tab", "switch"):
            kb.send("alt+tab")
            return "Switched active window."
        elif act in ("close_window", "close"):
            kb.send("alt+f4")
            return "Closed active window."
        return f"Unknown window action '{action}'."
    except Exception as exc:
        return f"Desktop window management failed: {exc}"


def get_weather(city: str = "") -> str:
    """Get current live weather condition and temperature for any city or local area."""
    import urllib.parse
    import urllib.request
    loc = urllib.parse.quote(city.strip()) if city and city.strip() else ""
    url = f"https://wttr.in/{loc}?format=%C:+%t+(feels+like+%f),+humidity+%h"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip()
            text = text.replace("°C", " degrees Celsius").replace("°F", " degrees Fahrenheit").replace("°", " degrees").replace("+", "")
            location_label = f" in {city.strip()}" if city and city.strip() else ""
            return f"Weather{location_label}: {text}"
    except Exception as exc:
        return f"Could not retrieve weather: {exc}"


def get_fact_summary(topic: str) -> str:
    """Fetch an authoritative, accurate, concise 1-2 sentence summary of any topic, historical event, person, or concept from Wikipedia."""
    import json
    import urllib.parse
    import urllib.request
    if not topic or not topic.strip():
        return "Please specify a topic."
    clean_topic = topic.strip().replace(" ", "_")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(clean_topic)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisAI/2.0 (desktop-assistant)"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            extract = data.get("extract", "").strip()
            if extract:
                sentences = re.split(r"(?<=[.!?])\s+", extract)
                return " ".join(sentences[:2])
            return f"No summary found for {topic}."
    except Exception:
        return f"Unable to retrieve summary for {topic}."


def search_files(query: str, root_folder: str = "") -> str:
    """Search for files and documents on the system matching a keyword or file name.
    Optionally restrict search to a specific folder path (defaults to Desktop, Documents, and Downloads).
    """
    payload = {"action": "explorer", "operation": "search", "query": query}
    if root_folder:
        payload["root_folder"] = root_folder
    res = dispatch(payload)
    return _format_result(res)


def describe_screen(query: str = "What is currently visible on my screen?") -> str:
    """Inspect and describe what is currently visible on the screen or answer questions about open windows, diagrams, code, or UI."""
    res = dispatch({"action": "vision", "operation": "describe_screen", "prompt": query})
    return _format_result(res)


def explain_screen_error(context: str = "") -> str:
    """Inspect the screen specifically for error dialogs, alert popups, red terminal stack traces, or exception messages, and explain the fix."""
    res = dispatch({"action": "vision", "operation": "explain_error", "context": context})
    return _format_result(res)


def read_screen_text(region: list = None) -> str:
    """Extract and read visible text from the entire screen or a specific region [x, y, width, height] using OCR or vision perception."""
    payload = {"action": "ocr", "operation": "read_screen"}
    if region:
        payload["operation"] = "read_region"
        payload["region"] = region
    res = dispatch(payload)
    if not res.get("success"):
        # Fall back to Gemini VLM vision text extraction
        v_payload = {"action": "vision", "operation": "read_text"}
        if region:
            v_payload["region"] = region
        res = dispatch(v_payload)
    return _format_result(res)


def run_workflow(name: str) -> str:
    """Execute a multi-step macro workflow by name (e.g. 'dev_workspace', 'goodnight_routine', 'meeting_mode', 'gaming_mode', 'morning_briefing')."""
    res = dispatch({"action": "macro", "operation": "run", "name": name})
    return _format_result(res)


def list_workflows() -> str:
    """List all available automated multi-step workflows and user macros."""
    res = dispatch({"action": "macro", "operation": "list"})
    return _format_result(res)


def create_custom_workflow(name: str, steps: list, description: str = "") -> str:
    """Create or save a new multi-step automated workflow macro. 'steps' is a list of action payload dictionaries."""
    res = dispatch({
        "action": "macro",
        "operation": "save",
        "name": name,
        "steps": steps,
        "description": description,
    })
    return _format_result(res)


def set_focus_mode(enable: bool, goal: str = "") -> str:
    """Enable or disable Focus / Do Not Disturb mode. When enabled, non-critical background notifications are silenced."""
    op = "enable_focus" if enable else "disable_focus"
    payload = {"action": "context", "operation": op}
    if goal and enable:
        payload["goal"] = goal
    res = dispatch(payload)
    return _format_result(res)


def get_focus_status() -> str:
    """Check the status of Focus Mode and how many minutes of focused work have elapsed."""
    res = dispatch({"action": "context", "operation": "get_focus_status"})
    return _format_result(res)


def get_user_presence() -> str:
    """Inspect user presence (active, idle, away) and seconds since last keyboard or mouse input."""
    res = dispatch({"action": "context", "operation": "get_presence"})
    return _format_result(res)


def get_ambient_context() -> str:
    """Get full ambient context: user presence, idle time, focus mode state, and quiet hours status."""
    res = dispatch({"action": "context", "operation": "get_ambient_context"})
    return _format_result(res)





def calculate(expression: str) -> str:
    """Safely calculate any math expression, percentage, power, or square root (e.g. '450 * 1.15', '2^16', 'sqrt(144) + 25')."""
    import math
    cleaned = expression.strip().replace("^", "**").replace("x", "*").replace("X", "*")
    if re.search(r"[^0-9\+\-\*\/\%\.\(\)\s,\*eE]|__", cleaned):
        allowed_names = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
        try:
            val = eval(cleaned, {"__builtins__": {}}, allowed_names)  # noqa: S307
            return f"The result is {round(val, 4) if isinstance(val, float) else val}."
        except Exception:
            return f"Could not calculate expression: {expression}"
    try:
        val = eval(cleaned, {"__builtins__": {}}, {})  # noqa: S307
        return f"The result is {round(val, 4) if isinstance(val, float) else val}."
    except Exception as exc:
        return f"Calculation error: {exc}"


def get_detailed_system_info() -> str:
    """Retrieve detailed hardware specs and disk usage for all partitions and drives (C:, D:, E:, F:)."""
    import platform
    import psutil
    uname = platform.uname()
    mem = psutil.virtual_memory()
    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            free_gb = round(u.free / (1024**3), 1)
            total_gb = round(u.total / (1024**3), 1)
            disks.append(f"{p.device} ({free_gb} GB free of {total_gb} GB)")
        except Exception:
            pass
    ram_free = round(mem.available / (1024**3), 1)
    ram_total = round(mem.total / (1024**3), 1)
    return (
        f"OS: {uname.system} {uname.release}. "
        f"RAM: {ram_free} GB free of {ram_total} GB. "
        f"Drives: {', '.join(disks)}."
    )


def quick_note(action: str, text: str = "") -> str:
    """Manage quick notes and reminders on the Desktop.
    'action' can be 'save' (saves a note with timestamp) or 'read' (reads recent notes).
    """
    notes_file = os.path.expanduser("~/Desktop/Jarvis_Notes.txt")
    if action.lower() in ("save", "add", "write", "create"):
        if not text:
            return "Please provide note text to save."
        timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        with open(notes_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {text.strip()}\n")
        return f"Note saved to Desktop: {text.strip()}"
    elif action.lower() in ("read", "view", "list", "show"):
        if not os.path.exists(notes_file):
            return "You have no saved notes on your Desktop, sir."
        with open(notes_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        recent = lines[-5:] if len(lines) > 5 else lines
        return "Recent notes: " + " | ".join(recent)
    return f"Unknown note action '{action}'. Supported: 'save', 'read'."


def set_timer(seconds: int, label: str = "") -> str:
    """Set an audible countdown timer or reminder for a number of seconds."""
    import winsound
    def _timer_callback():
        try:
            for _ in range(3):
                winsound.Beep(1200, 300)
                winsound.Beep(1600, 300)
        except Exception:
            pass
    t = threading.Timer(float(seconds), _timer_callback)
    t.daemon = True
    t.start()
    name = f" for '{label}'" if label else ""
    return f"Timer set{name} for {seconds} seconds, sir."


def search_web_summary(query: str) -> str:
    """Search the web for a quick factual summary or answer using DuckDuckGo Instant Answer without opening a browser."""
    import json
    import urllib.parse
    import urllib.request
    q = urllib.parse.quote(query.strip())
    url = f"https://api.duckduckgo.com/?q={q}&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisAI/2.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data.get("AbstractText") or data.get("Heading") or ""
            if answer:
                sentences = re.split(r"(?<=[.!?])\s+", answer)
                return " ".join(sentences[:2])
            return f"No direct summary found for '{query}'. I can search Google if you prefer."
    except Exception as exc:
        return f"Web search summary failed: {exc}"


def open_drive(letter: str) -> str:
    """Open any disk drive (C:, D:, E:, F:) directly in Windows File Explorer."""
    clean_letter = letter.upper().replace(":", "").replace("\\", "").strip()
    drive_path = f"{clean_letter}:\\"
    if os.path.exists(drive_path):
        os.startfile(drive_path)
        return f"Sir Abdullah, opened Drive {clean_letter}: in File Explorer."
    return f"Sir Abdullah, Drive {clean_letter}: was not found on this system."


def launch_system_utility(utility: str) -> str:
    """Launch built-in Windows administrative and diagnostic utilities.
    Supported 'utility' values:
    'task_manager', 'control_panel', 'device_manager', 'disk_management',
    'resource_monitor', 'registry_editor', 'disk_cleanup', 'event_viewer',
    'snipping_tool', 'directx_diag', 'calculator', 'notepad', 'paint'.
    """
    mapping = {
        "task_manager": "taskmgr",
        "taskmgr": "taskmgr",
        "control_panel": "control",
        "control": "control",
        "device_manager": "devmgmt.msc",
        "devmgmt": "devmgmt.msc",
        "disk_management": "diskmgmt.msc",
        "diskmgmt": "diskmgmt.msc",
        "resource_monitor": "resmon",
        "resmon": "resmon",
        "registry_editor": "regedit",
        "regedit": "regedit",
        "disk_cleanup": "cleanmgr",
        "cleanmgr": "cleanmgr",
        "event_viewer": "eventvwr.msc",
        "eventvwr": "eventvwr.msc",
        "snipping_tool": "snippingtool",
        "directx_diag": "dxdiag",
        "dxdiag": "dxdiag",
        "calculator": "calc",
        "calc": "calc",
        "notepad": "notepad",
        "paint": "mspaint",
    }
    cmd = mapping.get(utility.lower().strip().replace(" ", "_"))
    if not cmd:
        return f"Negative sir, unknown utility '{utility}'. Options: {', '.join(sorted(set(mapping.values())))}"
    try:
        subprocess.Popen([cmd], shell=True)
        return f"Positive sir, launched {utility}."
    except Exception as exc:
        return f"Negative sir, could not launch {utility}: {exc}"


def open_windows_settings(page: str = "") -> str:
    """Open specific Windows 11 Settings pages.
    Supported pages: 'bluetooth', 'wifi', 'network', 'sound', 'display', 'power',
    'battery', 'storage', 'apps', 'updates', 'notifications', 'personalization', 'mouse'.
    """
    settings_map = {
        "bluetooth": "ms-settings:bluetooth",
        "wifi": "ms-settings:network-wifi",
        "network": "ms-settings:network",
        "sound": "ms-settings:sound",
        "audio": "ms-settings:sound",
        "display": "ms-settings:display",
        "screen": "ms-settings:display",
        "power": "ms-settings:powersleep",
        "battery": "ms-settings:powersleep",
        "storage": "ms-settings:storagesense",
        "apps": "ms-settings:appsfeatures",
        "updates": "ms-settings:windowsupdate",
        "windows_update": "ms-settings:windowsupdate",
        "notifications": "ms-settings:notifications",
        "personalization": "ms-settings:personalization",
        "mouse": "ms-settings:mousetouchpad",
    }
    uri = settings_map.get(page.lower().strip().replace(" ", "_"), "ms-settings:")
    try:
        os.startfile(uri)
        target = page.title() if page else "Windows"
        return f"Positive sir, opened {target} Settings."
    except Exception as exc:
        return f"Negative sir, failed to open settings: {exc}"


def schedule_shutdown(minutes: int, action: str = "shutdown") -> str:
    """Schedule the computer to automatically shut down or restart after a specified number of minutes.
    'action' can be 'shutdown' (default) or 'restart'.
    """
    try:
        secs = max(1, int(float(minutes) * 60))
        flag = "/r" if action.lower() == "restart" else "/s"
        subprocess.run(["shutdown", flag, "/t", str(secs)], capture_output=True, text=True)
        verb = "restart" if flag == "/r" else "shut down"
        return f"Positive sir, your PC is scheduled to {verb} in {minutes} minute(s)."
    except Exception as exc:
        return f"Negative sir, failed to schedule shutdown: {exc}"


def cancel_scheduled_shutdown() -> str:
    """Cancel any pending or scheduled system shutdown or restart timer."""
    try:
        res = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
        if res.returncode == 0:
            return "Positive sir, scheduled shutdown has been cancelled."
        return "Positive sir, no shutdown was currently in progress."
    except Exception as exc:
        return f"Negative sir, failed to cancel shutdown: {exc}"


def network_flush_dns() -> str:
    """Flush and clear the Windows DNS resolver cache to resolve connectivity and website resolution issues."""
    try:
        res = subprocess.run(["ipconfig", "/flushdns"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return "Positive sir, the DNS resolver cache has been successfully flushed."
        return "Positive sir, DNS flush completed."
    except Exception as exc:
        return f"Negative sir, failed to flush DNS cache: {exc}"


def compress_or_extract_archive(action: str, source_path: str, destination_path: str = "") -> str:
    """Compress a folder/file into a .zip archive, or extract a .zip archive.
    - action='compress': compresses source_path into destination_path (or same directory with .zip)
    - action='extract': extracts source_path (.zip) into destination_path (or same directory)
    """
    import shutil
    import zipfile
    act = action.lower().strip()
    src = os.path.abspath(os.path.expanduser(source_path))
    if not os.path.exists(src):
        return f"Source path does not exist: {source_path}"

    try:
        if act in ("compress", "zip"):
            dest = destination_path or (src + ".zip" if os.path.isfile(src) else src)
            if dest.endswith(".zip"):
                dest = dest[:-4]
            if os.path.isdir(src):
                shutil.make_archive(dest, "zip", src)
                return f"Compressed folder into {dest}.zip"
            else:
                out_zip = dest + ".zip"
                with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(src, arcname=os.path.basename(src))
                return f"Compressed file into {out_zip}"
        elif act in ("extract", "unzip"):
            dest = destination_path or os.path.splitext(src)[0]
            os.makedirs(dest, exist_ok=True)
            shutil.unpack_archive(src, dest)
            return f"Extracted archive into {dest}"
        return f"Unknown archive action '{action}'. Supported: 'compress', 'extract'."
    except Exception as exc:
        return f"Archive operation failed: {exc}"


def create_desktop_shortcut(name: str, target_path: str) -> str:
    """Create a Windows desktop shortcut (.lnk) pointing to any file, application, folder, or executable."""
    try:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        desktop = os.path.expanduser("~/Desktop")
        clean_name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
        if not clean_name.lower().endswith(".lnk"):
            clean_name += ".lnk"
        shortcut_path = os.path.join(desktop, clean_name)

        shell = comtypes.client.CreateObject("WScript.Shell")
        shortcut = shell.CreateShortcut(shortcut_path)
        shortcut.TargetPath = target_path
        shortcut.Save()
        return f"Sir Abdullah, desktop shortcut '{clean_name}' created successfully."
    except Exception as exc:
        return f"Failed to create shortcut: {exc}"


def download_file_from_web(url: str, filename: str = "", destination_folder: str = "") -> str:
    """Download a file from any web URL directly into the user's Downloads or target directory."""
    import urllib.parse
    import urllib.request
    try:
        parsed = urllib.parse.urlparse(url)
        auto_name = os.path.basename(parsed.path) or "downloaded_file"
        dest_name = filename or auto_name
        dest_folder = destination_folder or os.path.expanduser("~/Downloads")
        os.makedirs(dest_folder, exist_ok=True)
        target_path = os.path.join(dest_folder, dest_name)

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp, open(target_path, "wb") as f:
            f.write(resp.read())
        size_kb = round(os.path.getsize(target_path) / 1024, 1)
        return f"Sir Abdullah, downloaded '{dest_name}' ({size_kb} KB) to {dest_folder}."
    except Exception as exc:
        return f"Failed to download file: {exc}"


def type_text_into_active_window(text: str, press_enter: bool = False) -> str:
    """Type text directly into the currently focused active window, with optional Enter keypress."""
    import keyboard as kb
    if not text:
        return "No text provided to type."
    kb.write(text)
    if press_enter:
        kb.send("enter")
    return f"Typed {len(text)} character(s) into active window."


def kill_process_by_pid(pid: int) -> str:
    """Forcefully terminate or kill a specific process ID."""
    import psutil
    try:
        p = psutil.Process(int(pid))
        p_name = p.name()
        p.terminate()
        return f"Terminated process '{p_name}' (PID {pid})."
    except psutil.NoSuchProcess:
        return f"No active process with PID {pid} found."
    except Exception as exc:
        return f"Could not terminate PID {pid}: {exc}"


def list_connected_audio_devices() -> str:
    """List connected audio speakers, headphones, and microphones."""
    import sounddevice as sd
    try:
        devices = sd.query_devices()
        outputs = []
        inputs = []
        for d in devices:
            name = d.get("name", "")
            if d.get("max_output_channels", 0) > 0 and name not in outputs:
                outputs.append(name)
            if d.get("max_input_channels", 0) > 0 and name not in inputs:
                inputs.append(name)
        out_summary = ", ".join(outputs[:4]) if outputs else "None"
        in_summary = ", ".join(inputs[:4]) if inputs else "None"
        return f"Audio Outputs: {out_summary}. Microphones: {in_summary}."
    except Exception as exc:
        return f"Failed to list audio devices: {exc}"


def execute_windows_command(request: str, confirmed: bool = False) -> str:
    """Execute or query a Windows CMD or PowerShell command using the Windows Command Master Knowledge Base.
    Understands natural language requests (e.g. 'what is my IP', 'which process is using port 5000',
    'show running processes', 'create folder Projects on desktop', 'check my internet', 'find Python').
    Validates safety and 4-tier risk levels (LOW, MEDIUM, HIGH, CRITICAL). If a command requires user
    confirmation, it asks before running.
    """
    res = dispatch({
        "action": "command",
        "operation": "execute",
        "request": request,
        "confirmed": confirmed,
    })
    return _format_result(res)


def search_windows_commands(query: str, limit: int = 5) -> str:
    """Search the Windows Command Master Knowledge Base (492 reference commands across networking,
    diagnostics, developer tools, PowerShell, disk management, repair, and Windows administration).
    """
    res = dispatch({
        "action": "command",
        "operation": "search",
        "query": query,
        "limit": limit,
    })
    return _format_result(res)


ALL_TOOLS = [
    execute_windows_command,
    search_windows_commands,
    open_app,
    close_app,
    open_drive,
    list_running_apps,
    empty_recycle_bin,
    set_screen_brightness,
    get_wifi_status,
    network_ping,
    get_ip_address,
    network_flush_dns,
    manage_desktop_window,
    launch_system_utility,
    open_windows_settings,
    schedule_shutdown,
    cancel_scheduled_shutdown,
    compress_or_extract_archive,
    create_desktop_shortcut,
    download_file_from_web,
    type_text_into_active_window,
    kill_process_by_pid,
    list_connected_audio_devices,
    get_weather,
    get_fact_summary,
    search_files,
    read_screen_text,
    describe_screen,
    explain_screen_error,
    run_workflow,
    list_workflows,
    create_custom_workflow,
    set_focus_mode,
    get_focus_status,
    get_user_presence,
    get_ambient_context,
    calculate,
    get_detailed_system_info,
    quick_note,
    set_timer,
    search_web_summary,
    search_google,
    search_youtube,
    open_url,
    set_volume,
    adjust_volume,
    media_control,
    get_news,
    run_command,
    get_system_status,
    system_power,
    manage_files,
    control_keyboard,
    control_mouse,
    clipboard_action,
    take_screenshot,
]


def check_fast_path(text: str) -> Optional[str]:
    """Provides instant (0-5ms) local execution for high-frequency queries,
    completely bypassing cloud API roundtrips for maximum responsiveness."""
    lowered = text.lower().strip()
    clean_alpha = re.sub(r"[^a-z]", "", lowered)

    # 0. Wake-up and status check queries: "wake up", "wake up jarvis", "are you awake", "are you there", "status check"
    if lowered in (
        "wake up",
        "wake up jarvis",
        "jarvis wake up",
        "are you awake",
        "are you there",
        "are you online",
        "status check",
        "system check",
        "systems check",
    ) or clean_alpha in ("wakeup", "wakeupjarvis", "jarviswakeup", "areyouthere", "areyouawake"):
        return "Sir Abdullah, I am awake and all systems are fully operational."

    if lowered in ("hello", "hello jarvis", "hi jarvis", "hey jarvis") or clean_alpha in ("hello", "hellojarvis", "hijarvis", "heyjarvis"):
        return "At your service, Sir Abdullah. How may I assist you?"

    if lowered in ("who are you", "what are you", "what is your name"):
        return "I am JARVIS, your personal desktop automation AI assistant."

    if lowered in ("how are you", "how are you doing", "how do you do"):
        return "All systems functioning at peak efficiency, sir. How may I be of service?"

    # 0.1 Language mode switching fast-paths:
    if lowered in ("speak in urdu", "talk in urdu", "switch to urdu", "urdu mein baat karo", "urdu bolo", "urdu mein bolo") or any(k in lowered for k in ("اردو میں بات کرو", "اردو بولو")):
        return "Jee Sir Abdullah, ab se main aapse Roman Urdu mein baat karunga. Farmaiye, kya hukum hai?"

    if lowered in ("speak in english", "talk in english", "switch to english", "english bolo", "english mein baat karo") or any(k in lowered for k in ("انگلش میں بات کرو", "انگلش بولو")):
        return "Positive sir, switching back to English. Standing by for your commands."

    # 0.2 Bilingual (Urdu / Roman Urdu / Hinglish) greetings and status checks:
    if lowered in (
        "kya haal hai",
        "kaise ho",
        "kya chal raha hai",
        "kya hal hai",
        "kaise hain",
        "kya chal rha hai",
        "haal kaisa hai",
        "sab theek hai",
        "kia hal hai",
        "kia haal hai",
    ) or any(k in lowered for k in ("kya haal", "kaise ho", "kya chal raha", "sab theek hai")):
        return "Jee Sir Abdullah, main bilkul theek hoon. Sub kuch behtareen chal raha hai. Aap batayein, kya khidmat karoon?"

    if lowered in ("tum kaun ho", "kaun ho tum", "apna naam batao", "aap kon hain", "kon ho tum"):
        return "Jee Sir Abdullah, main JARVIS hoon, aapka personal AI assistant. Batayein, kya hukum hai?"

    if lowered in ("kya kar rahe ho", "kya kar sakte ho", "tum kya kar sakte ho"):
        return "Jee Sir Abdullah, main aapke desktop ke tamam kaam, applications, volume, aur settings control karne ke liye tayyar hoon."

    if any(k in lowered for k in ("کیا حال ہے", "کیسے ہو", "سب ٹھیک ہے")):
        return "Jee Sir Abdullah, main bilkul theek hoon. Sub kuch behtareen chal raha hai. Aap batayein, kya khidmat karoon?"
    if any(k in lowered for k in ("کون ہو تم", "تم کون ہو", "اپنا نام بتاؤ")):
        return "Jee Sir Abdullah, main JARVIS hoon, aapka personal AI assistant. Batayein, kya hukum hai?"

    # 1. IP Address queries: "what is my public ip", "what is my private ip", "what is my ip", etc.
    # Exclude conceptual questions like "what is ipv4" or "explain ipv4"
    if re.search(r"\b(ip|ipv4|ipv6|address)\b", lowered):
        is_my_ip = any(k in lowered for k in ("my", "local", "private", "public", "external", "wan", "machine", "this pc", "address"))
        is_not_explanation = not any(k in lowered for k in ("what is ipv", "difference", "explain", "meaning", "definition"))
        if is_my_ip and is_not_explanation:
            if re.search(r"\b(?:public|external|wan|global|internet)\b", lowered):
                return get_ip_address(ip_type="public")
            if re.search(r"\b(?:private|local|internal|lan)\b", lowered):
                return get_ip_address(ip_type="private")
            if re.search(r"\bipv4\b", lowered):
                return get_ip_address(ip_type="private")
            return get_ip_address(ip_type="all")

    # 2. Time queries: "what is the time", "tell me the time", "current time", "kya time hai", "waqt batao"
    if (re.search(r"\b(time|what time|waqt)\b", lowered) and any(k in lowered for k in ("what", "tell", "current", "now", "kya", "batao", "kia"))) or any(k in lowered for k in ("وقت کیا ہوا", "ٹائم کیا ہوا")):
        now_str = datetime.now().strftime("%I:%M %p")
        if any(re.search(pat, lowered) for pat in (r"\bwaqt\b", r"\bbatao\b", r"\bkya\b", r"\bkia\b", r"وقت", r"ٹائم")):
            return f"Jee Sir Abdullah, is waqt {now_str} ho rahe hain."
        return f"Positive sir, the current time is {now_str}."

    # 3. Date queries: "what is today's date", "what day is today", "aaj kya tareekh hai"
    if (re.search(r"\b(date|what day|tareekh)\b", lowered) and any(k in lowered for k in ("what", "today", "current", "kya", "aaj", "konsa", "kia"))) or any(k in lowered for k in ("آج کیا تاریخ ہے", "تاریخ کیا ہے")):
        today_str = datetime.now().strftime("%A, %B %d, %Y")
        if any(re.search(pat, lowered) for pat in (r"\btareekh\b", r"\baaj\b", r"\bkonsa\b", r"\bkia\b", r"\bkya\b", r"تاریخ")):
            return f"Jee Sir Abdullah, aaj {today_str} hai."
        return f"Positive sir, today is {today_str}."

    # 4. Battery queries: "how much battery", "battery percentage", "battery status"
    if "battery" in lowered:
        import psutil
        batt = psutil.sensors_battery()
        if batt:
            status = "plugged in" if batt.power_plugged else "discharging"
            return f"Positive sir, your battery is at {round(batt.percent)}% and currently {status}."

    # 5. Fast volume controls:
    if any(k in lowered for k in ("volume", "audio", "sound", "awaz", "aawaz", "آواز")):
        if any(k in lowered for k in ("mute", "unmute", "silence", "band karo", "band kardo", "بند کرو")):
            from actions.system import volume_mute
            volume_mute()
            if any(k in lowered for k in ("awaz", "aawaz", "band", "آواز")):
                return "Jee Sir Abdullah, aawaz band kar di hai."
            return "Positive sir, audio mute toggled."
        if any(k in lowered for k in ("up", "increase", "higher", "raise", "boost", "barhao", "barha do", "zyada karo", "tez karo", "بڑھاؤ")):
            from actions.system import volume_up
            volume_up()
            if any(k in lowered for k in ("awaz", "aawaz", "barha", "tez", "zyada", "آواز")):
                return "Jee Sir Abdullah, volume barha diya hai."
            return "Positive sir, volume increased."
        if any(k in lowered for k in ("down", "decrease", "lower", "reduce", "kam karo", "kam kardo", "dheema karo", "کم کرو")):
            from actions.system import volume_down
            volume_down()
            if any(k in lowered for k in ("awaz", "aawaz", "kam", "dheema", "کم کرو", "آواز")):
                return "Jee Sir Abdullah, volume kam kar diya hai."
            return "Positive sir, volume decreased."

    # 6. Recycle bin: "empty recycle bin", "clean recycle bin", "empty bin", "recycle bin saaf karo"
    if any(k in lowered for k in ("empty recycle bin", "empty the recycle bin", "clean recycle bin", "empty bin", "recycle bin saaf", "kachra saaf")):
        from actions.system import _empty_recycle_bin
        _empty_recycle_bin()
        if any(k in lowered for k in ("saaf", "kachra")):
            return "Jee Sir Abdullah, recycle bin saaf ho gaya hai."
        return "Positive sir, the Recycle Bin has been emptied."

    # 7. Desktop window management:
    if any(k in lowered for k in ("minimize all", "show desktop", "minimize windows", "hide all windows", "clear desktop", "windows minimize karo", "desktop dikhao")):
        try:
            import comtypes.client
            comtypes.CoInitialize()
            shell = comtypes.client.CreateObject("Shell.Application")
            shell.MinimizeAll()
            if any(k in lowered for k in ("karo", "dikhao")):
                return "Jee Sir Abdullah, saari windows minimize kar di hain."
            return "Positive sir, all windows have been minimized."
        except Exception:
            pass

    if any(k in lowered for k in ("restore windows", "unminimize", "show windows")):
        try:
            import comtypes.client
            comtypes.CoInitialize()
            shell = comtypes.client.CreateObject("Shell.Application")
            shell.UndoMinimizeALL()
            return "Positive sir, windows restored."
        except Exception:
            pass

    # 8. Wi-Fi & Internet status:
    if re.search(r"\b(wifi|wi-fi|internet)\b", lowered) and any(k in lowered for k in ("status", "check", "connected", "state", "signal")):
        from actions.system import _wifi_info
        info = _wifi_info()
        if info.get("success") and info.get("ssid") != "Not connected":
            return f"Positive sir, your Wi-Fi is connected to {info.get('ssid')} with {info.get('signal')} signal."
        return "Negative sir, your Wi-Fi is currently disconnected."

    # 9. Disk space / drive storage queries:
    if any(k in lowered for k in ("disk space", "storage", "free space", "drive space", "how much space", "hard drive space")):
        return f"Positive sir, {get_detailed_system_info()}"

    # 10. Drive opening queries: "open drive F", "open drive C", "open F drive", "Open C, drive", "open local disk D", etc.
    if not any(k in lowered for k in ("space", "storage", "driver", "driven")):
        drive_match = re.search(
            r"\b(?:open\s+)?(?:drive\s+([a-zA-Z])\b|([a-zA-Z])\s*[,:]?\s*drive\b|local\s+disk\s+([a-zA-Z])\b)",
            lowered,
        )
        if drive_match:
            letter = (drive_match.group(1) or drive_match.group(2) or drive_match.group(3)).upper()
            if letter != "S" or "drive s" in lowered:
                drive_path = f"{letter}:\\"
                if os.path.exists(drive_path):
                    try:
                        os.startfile(drive_path)
                        return f"Positive sir, opened Drive {letter}: in File Explorer."
                    except Exception as e:
                        return f"Negative sir, opened Drive {letter}:, but encountered an issue: {e}"
                else:
                    return f"Negative sir, Drive {letter}: was not found on this system."

    # 10. Common speech mishearings for Drive F or File Explorer:
    if re.search(r"\bopen\s+(?:the\s+)?drive\s+app\b", lowered) or lowered in ("open drive app", "drive app", "the drive app"):
        if os.path.exists("F:\\"):
            os.startfile("F:\\")
            return "Positive sir, opened Drive F: in File Explorer."
        subprocess.Popen(["explorer.exe"])
        return "Positive sir, opened File Explorer."

    # 11. File Explorer / This PC queries:
    if re.search(r"\bopen\s+(?:file\s+explorer|this\s+pc|my\s+computer|drives)\b", lowered):
        subprocess.Popen(["explorer.exe", "shell:MyComputerFolder"])
        return "Positive sir, opened This PC in File Explorer."

    # 12. Weather fast-path:
    if re.search(r"\b(weather|temperature)\b", lowered) and any(k in lowered for k in ("what", "tell", "current", "how", "what's", "is it")):
        city_m = re.search(r"\b(?:in|for)\s+([a-zA-Z\s]+)", lowered)
        city = city_m.group(1).strip() if city_m else ""
        report = get_weather(city)
        return f"Positive sir, {report}."

    # 13. System Utilities fast-path:
    if re.search(r"\b(?:open\s+)?task\s*manager\b", lowered) or clean_alpha == "taskmanager":
        return launch_system_utility("task_manager")
    if re.search(r"\b(?:open\s+)?control\s*panel\b", lowered) or clean_alpha == "controlpanel":
        return launch_system_utility("control_panel")
    if re.search(r"\b(?:open\s+)?device\s*manager\b", lowered) or clean_alpha == "devicemanager":
        return launch_system_utility("device_manager")
    if re.search(r"\b(?:open\s+)?resource\s*monitor\b", lowered) or clean_alpha == "resourcemonitor":
        return launch_system_utility("resource_monitor")
    if re.search(r"\b(?:open\s+)?registry\s*editor\b", lowered) or clean_alpha == "registryeditor":
        return launch_system_utility("registry_editor")

    # 14. Network DNS flush:
    if any(k in lowered for k in ("flush dns", "clear dns", "reset dns")):
        return network_flush_dns()

    # 15. Cancel shutdown:
    if any(k in lowered for k in ("cancel shutdown", "abort shutdown", "stop shutdown")):
        return cancel_scheduled_shutdown()

    # 16. Windows Settings fast-path:
    settings_m = re.search(r"\bopen\s+([a-zA-Z\s]+)\s+settings\b", lowered)
    if settings_m:
        return open_windows_settings(settings_m.group(1).strip())

    # 17. Windows Command Knowledge Base fast-paths (0ms local execution):
    # Port process lookup: e.g. "which process is using port 5000", "find process using port 8080", "check port 3000"
    if "port" in lowered and re.search(r"\b\d{2,5}\b", lowered):
        return execute_windows_command(text)

    # Running processes: e.g. "show me all running processes", "what programs are running"
    if any(k in lowered for k in ("running processes", "what programs are running", "show all processes")):
        return execute_windows_command(text)

    # Internet connectivity: e.g. "check my internet", "test internet connectivity"
    if any(k in lowered for k in ("check my internet", "test internet connectivity", "is internet working")):
        return execute_windows_command(text)

    # Specific local IP lookup: e.g. "what is my local ip", "show my local ip", "private ip"
    if any(k in lowered for k in ("local ip", "private ip", "internal ip")):
        return execute_windows_command("what is my IP")

    # 18. Screen perception & visual QA fast-paths:
    if re.search(r"\b(?:what(?:'s|\s+is)\s+on\s+my\s+screen|describe\s+(?:my\s+)?screen|look\s+at\s+my\s+screen|what\s+do\s+you\s+see\s+on\s+my\s+screen|screen\s+par\s+kya\s+hai|screen\s+dikhao|screen\s+check\s+karo)\b", lowered) or any(k in lowered for k in ("سکرین پر کیا ہے", "سکرین دیکھو")):
        return describe_screen(text)

    if re.search(r"\b(?:explain\s+(?:this\s+|the\s+)?error|what\s+is\s+this\s+error|explain\s+screen\s+error)\b", lowered):
        return explain_screen_error(text)

    # 19. Multi-step macro & workflow automation fast-paths:
    if re.search(r"\b(?:prepare|setup|start)\s+(?:the\s+|my\s+)?(?:dev|development|coding)\s+(?:workspace|environment|mode)\b", lowered) or lowered in ("dev mode", "dev workspace", "prepare dev workspace", "coding mode"):
        return run_workflow("dev_workspace")

    if re.search(r"\b(?:good\s*night(?:\s+routine)?|bedtime\s+routine|bedtime\s+mode|sleep\s+routine)\b", lowered):
        return run_workflow("goodnight_routine")

    if re.search(r"\b(?:meeting\s+mode|start\s+(?:the\s+)?meeting|prep(?:are)?\s+meeting)\b", lowered):
        return run_workflow("meeting_mode")

    if re.search(r"\b(?:gaming\s+mode|game\s+mode|start\s+gaming)\b", lowered):
        return run_workflow("gaming_mode")

    if re.search(r"\b(?:morning\s+briefing|morning\s+routine|start\s+my\s+day)\b", lowered):
        return run_workflow("morning_briefing")

    if re.search(r"\b(?:list\s+(?:all\s+)?(?:workflows|macros)|show\s+(?:my\s+)?(?:workflows|macros))\b", lowered):
        return list_workflows()

    # 20. Ambient context & Focus/DND mode fast-paths:
    if re.search(r"\b(?:start|enter|enable|activate|turn\s+on)\s+(?:focus\s+mode|dnd|do\s+not\s+disturb)\b", lowered) or lowered in ("focus mode", "focus mode on", "enable dnd", "do not disturb on"):
        goal_m = re.search(r"\b(?:focus\s+mode|dnd|do\s+not\s+disturb)\s+(?:for|to|on)\s+(.+)", lowered)
        goal = goal_m.group(1).strip() if goal_m else ""
        return set_focus_mode(True, goal)

    if re.search(r"\b(?:stop|exit|disable|deactivate|turn\s+off)\s+(?:focus\s+mode|dnd|do\s+not\s+disturb)\b", lowered) or lowered in ("focus mode off", "disable dnd", "do not disturb off", "exit focus"):
        return set_focus_mode(False)

    if re.search(r"\b(?:focus\s+(?:status|state)|how\s+long\s+have\s+i\s+been\s+focusing|am\s+i\s+in\s+focus\s+mode)\b", lowered):
        return get_focus_status()

    if re.search(r"\b(?:am\s+i\s+idle|check\s+presence|how\s+long\s+have\s+i\s+been\s+idle|user\s+presence)\b", lowered):
        return get_user_presence()

    if re.search(r"\b(?:ambient\s+context|ambient\s+status|context\s+status)\b", lowered):
        return get_ambient_context()

    return None





class JarvisAgent:
    """Autonomous JARVIS agent powered by the Google GenAI SDK."""

    def __init__(self, api_key: str = None, model: str = None) -> None:
        self.api_key = api_key or config.GEMINI_API_KEY
        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured. Please add GEMINI_API_KEY to your .env file."
            )
        self.model_name = model or config.JARVIS_GEMINI_MODEL or "gemini-2.5-flash"
        self._client = genai.Client(api_key=self.api_key)
        self._chat = None
        self._init_chat()

    def _init_chat(self, model: str = None) -> None:
        target_model = model or self.model_name
        extra_kwargs = {}
        if "2.5-flash" in target_model:
            extra_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

        chat_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=ALL_TOOLS,
            temperature=0.2,
            **extra_kwargs,
        )
        self._chat = self._client.chats.create(
            model=target_model,
            config=chat_config,
        )
        self.model_name = target_model

    def reset_chat(self) -> None:
        """Clears the multi-turn chat history."""
        self._init_chat()

    def chat(self, user_message: str) -> str:
        """Sends a message to the agent, automatically invokes any needed tools,
        and returns the final response string. Automatically falls back to secondary models if quota/429 occurs.
        Enforces clean, punchy spoken brevity (1-2 sentences max).
        """
        text = (user_message or "").strip()
        if not text:
            return "Sir, I didn't catch that. Could you please repeat?"

        fast_reply = check_fast_path(text)
        if fast_reply:
            return fast_reply

        if self._chat is None:
            self._init_chat()

        models_to_try = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
        last_error = None

        import concurrent.futures

        for candidate_model in models_to_try:
            try:
                if self.model_name != candidate_model:
                    logger.info("Switching to fallback model: %s", candidate_model)
                    self._init_chat(model=candidate_model)

                agent_timeout = float(os.getenv("JARVIS_AGENT_TIMEOUT", "25.0"))
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._chat.send_message, text)
                    try:
                        response = future.result(timeout=agent_timeout)
                    except concurrent.futures.TimeoutError:
                        logger.warning(
                            "Model %s request timed out after %ds; attempting fallback...",
                            candidate_model,
                            int(agent_timeout),
                        )
                        continue

                reply = (response.text or "").strip()
                if not reply:
                    return "Action completed, sir."

                # Clean markdown characters for crystal-clear voice synthesis
                clean_reply = re.sub(r"[\*#`_]", "", reply).strip()

                # Enforce concise spoken brevity: keep to 1-2 sentences unless in-depth analysis was requested
                detailed_keys = ("explain in detail", "elaborate", "long answer", "essay", "in depth", "thoroughly")
                if not any(k in text.lower() for k in detailed_keys):
                    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_reply) if s.strip()]
                    if len(sentences) > 2:
                        clean_reply = " ".join(sentences[:2])

                return clean_reply
            except Exception as exc:
                err_str = str(exc)
                last_error = exc
                logger.warning(
                    "Model %s encountered error (%s); trying next available fallback model...",
                    candidate_model,
                    err_str[:120],
                )
                continue

        return f"Negative, sir. All available models hit quota or error: {last_error}"


_agent_instance = None
_agent_lock = threading.Lock()


def get_agent() -> JarvisAgent:
    """Returns the singleton JarvisAgent instance with thread safety."""
    global _agent_instance
    if _agent_instance is None:
        with _agent_lock:
            if _agent_instance is None:
                _agent_instance = JarvisAgent()
    return _agent_instance
