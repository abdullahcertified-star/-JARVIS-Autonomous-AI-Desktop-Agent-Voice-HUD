"""JARVIS interface: a Next.js/Three.js app (voice/web/) rendered in a
native pywebview window, showing a glowing particle sphere that reacts to
voice state (booting/idle/listening/thinking/speaking/error), plus a real
scrolling conversation log and a dashboard view.

Python still does 100% of the actual work (mic, wake word, transcription,
TTS) -- this module is purely the visual layer plus the thin bridge that
drives it. voice/main.py calls JarvisWindow.set_state()/set_level()/
add_message() exactly as before; those still map to the same-named global
JS functions (see voice/web/lib/bridge.ts), just running inside the
Next.js page instead of a hand-written HTML string now.
"""

from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path
from typing import Literal, Optional

import webview

State = Literal["booting", "idle", "listening", "thinking", "speaking", "error"]

_WEB_OUT_DIR = Path(__file__).parent / "web" / "out"

_active_window_instance: Optional["JarvisWindow"] = None


def get_active_window() -> Optional["JarvisWindow"]:
    """Returns the active JarvisWindow instance if the HUD is open."""
    return _active_window_instance



def _start_static_server(directory: Path) -> int:
    """Serves the Next.js static export on 127.0.0.1 on a free port,
    returning that port. Runs on a daemon thread -- no explicit shutdown
    needed, it dies with the process. A real HTTP server (not a bare
    file:// load) is required here because the exported build references
    its JS/CSS with root-absolute paths like /_next/static/..."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server.server_address[1]


class _Api:
    def __init__(
        self,
        window: webview.Window,
        muted_event: threading.Event,
        window_wrapper: Optional["JarvisWindow"] = None,
    ) -> None:
        self._window = window
        self._muted_event = muted_event
        self._window_wrapper = window_wrapper
        self._is_fullscreen = False

    def close(self) -> None:
        self._window.destroy()

    def minimize(self) -> None:
        try:
            self._window.minimize()
        except Exception:
            pass

    def maximize(self) -> None:
        try:
            self._window.maximize()
        except Exception:
            pass

    def toggle_fullscreen(self) -> bool:
        try:
            self._window.toggle_fullscreen()
            self._is_fullscreen = not self._is_fullscreen
            return self._is_fullscreen
        except Exception:
            return False

    def restore_window(self) -> None:
        try:
            self._window.restore()
        except Exception:
            pass

    def resize_window(self, width: int, height: int) -> None:
        try:
            self._window.restore()
        except Exception:
            pass
        try:
            self._window.resize(width, height)
        except Exception:
            pass

    def toggle_mute(self) -> None:
        if self._muted_event.is_set():
            self._muted_event.clear()
        else:
            self._muted_event.set()
        self._window.evaluate_js(f"setMuted({'true' if self._muted_event.is_set() else 'false'})")

    def toggle_system_mute(self) -> dict:
        try:
            from actions.system import volume_mute
            return volume_mute({})
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def set_volume(self, level: int) -> dict:
        try:
            from actions.system import _set_volume
            return _set_volume({"level": level})
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def get_system_telemetry(self) -> dict:
        try:
            from dispatcher import dispatch
            import config
            from voice import config as vconfig
            import psutil
            import socket
            import ctypes

            status = dispatch({"action": "system", "operation": "status"})
            
            disk_percent = 0.0
            disk_free_gb = 0.0
            disk_total_gb = 0.0
            try:
                disk = psutil.disk_usage("C:\\")
                disk_percent = round(disk.percent, 1)
                disk_free_gb = round(disk.free / (1024**3), 1)
                disk_total_gb = round(disk.total / (1024**3), 1)
            except Exception:
                pass

            mem_used_gb = 0.0
            mem_total_gb = 0.0
            try:
                mem = psutil.virtual_memory()
                mem_used_gb = round(mem.used / (1024**3), 1)
                mem_total_gb = round(mem.total / (1024**3), 1)
            except Exception:
                pass

            ip_addr = "127.0.0.1"
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.1)
                s.connect(("8.8.8.8", 80))
                ip_addr = s.getsockname()[0]
                s.close()
            except Exception:
                pass

            active_window = "JARVIS System Core"
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    if buff.value:
                        active_window = buff.value[:45]
            except Exception:
                pass

            volume_val = status.get("volume_percent")
            if volume_val is None:
                volume_val = status.get("volume", 50)

            return {
                "success": True,
                "cpu_percent": round(status.get("cpu_percent", 0), 1),
                "memory_percent": round(status.get("memory_percent", 0), 1),
                "memory_used_gb": mem_used_gb,
                "memory_total_gb": mem_total_gb,
                "disk_percent": disk_percent,
                "disk_free_gb": disk_free_gb,
                "disk_total_gb": disk_total_gb,
                "battery_percent": status.get("battery_percent"),
                "uptime_seconds": status.get("uptime_seconds", 0),
                "volume": volume_val,
                "system_muted": status.get("muted", False),
                "mic_muted": self._muted_event.is_set(),
                "process_count": len(psutil.pids()),
                "ip_address": ip_addr,
                "active_window": active_window,
                "agent_model": getattr(config, "JARVIS_GEMINI_MODEL", "gemini-3.5-flash-lite"),
                "tts_voice": getattr(vconfig, "EDGE_VOICE", "en-GB-RyanNeural"),
                "tts_pitch": getattr(vconfig, "EDGE_PITCH", "-35Hz"),
                "whisper_model": getattr(vconfig, "WHISPER_MODEL_SIZE", "base.en"),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def execute_action(self, payload: dict) -> dict:
        try:
            from dispatcher import dispatch
            return dispatch(payload)
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def send_chat(self, text: str) -> dict:
        try:
            from voice.pipeline import send_to_jarvis, Speaker, classify_reply
            clean_text = text.strip()
            if not clean_text:
                return {"success": False, "message": "Empty message"}

            escaped_prompt = clean_text.replace("\\", "\\\\").replace("'", "\\'")
            self._window.evaluate_js(f"addMessage('you', '{escaped_prompt}', 'positive')")
            self._window.evaluate_js("setState('thinking')")
            
            reply = send_to_jarvis(clean_text)
            tone = classify_reply(reply or "")
            escaped_reply = (reply or "").replace("\\", "\\\\").replace("'", "\\'").replace("\n", "<br>")

            displayed = False
            def on_speech_start() -> None:
                nonlocal displayed
                if not displayed:
                    self._window.evaluate_js(f"addMessage('jarvis', '{escaped_reply}', '{tone}')")
                    self._window.evaluate_js("setState('speaking')")
                    displayed = True

            try:
                Speaker().say(reply, on_start=on_speech_start)
            except Exception:
                pass

            if not displayed:
                self._window.evaluate_js(f"addMessage('jarvis', '{escaped_reply}', '{tone}')")

            self._window.evaluate_js("setState('idle')")
            return {"success": True, "reply": reply}
        except Exception as exc:
            self._window.evaluate_js("setState('error')")
            return {"success": False, "message": str(exc)}

    def resolve_confirmation(self, confirmation_id: str, approved: bool) -> dict:
        if self._window_wrapper:
            return self._window_wrapper.resolve_confirmation(confirmation_id, approved)
        return {"success": False, "message": "Window wrapper not connected"}



class JarvisWindow:
    """Thin wrapper around the pywebview window + JS calls to drive it."""

    def __init__(self) -> None:
        if not (_WEB_OUT_DIR / "index.html").exists():
            raise RuntimeError(
                f"{_WEB_OUT_DIR} doesn't have a built app. Run:\n"
                "  cd voice/web && npm install && npm run build"
            )

        # Set by the mute button; voice/audio.py's WakeWordListener checks
        # this and just discards mic frames while it's set, without closing
        # the stream -- muting doesn't stop the app, just pauses listening.
        self.muted = threading.Event()

        port = _start_static_server(_WEB_OUT_DIR)
        self._window = webview.create_window(
            "JARVIS",
            url=f"http://127.0.0.1:{port}/",
            width=1240,
            height=820,
            resizable=True,
            min_size=(460, 580),
            frameless=True,
            easy_drag=True,
            on_top=False,
            shadow=True,
            background_color="#04060a",
        )
        global _active_window_instance
        _active_window_instance = self
        self._pending_confirmations: dict[str, dict] = {}
        self._confirmation_lock = threading.Lock()
        self.current_state: State = "booting"

        api = _Api(self._window, self.muted, self)
        self._window.expose(
            api.close,
            api.minimize,
            api.maximize,
            api.toggle_fullscreen,
            api.restore_window,
            api.resize_window,
            api.toggle_mute,
            api.toggle_system_mute,
            api.set_volume,
            api.get_system_telemetry,
            api.execute_action,
            api.send_chat,
            api.resolve_confirmation,
        )

    def on_close(self, callback) -> None:
        """Registers callback() to run when the window starts closing --
        the only reliable shutdown signal for a background-thread voice
        loop, since Ctrl+C in the console never reaches a background thread."""
        self._window.events.closing += lambda: callback()

    def start(self, target, args: tuple = ()) -> None:
        """Blocks the calling (main) thread running the native GUI loop;
        `target` runs on a background thread once the window is ready."""
        webview.start(target, args, gui="edgechromium")

    def close(self) -> None:
        global _active_window_instance
        _active_window_instance = None
        try:
            self._window.destroy()
        except Exception:
            pass

    def show_confirmation(
        self,
        req_id: str,
        command: str,
        shell: str,
        risk_level: str,
        reason: str,
        timeout_seconds: int = 20,
    ) -> None:
        try:
            escaped_cmd = command.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
            escaped_reason = reason.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
            self._window.evaluate_js(
                f"showConfirmation('{req_id}', '{escaped_cmd}', '{shell}', '{risk_level}', '{escaped_reason}', {timeout_seconds})"
            )
        except Exception:
            pass

    def hide_confirmation(self) -> None:
        try:
            self._window.evaluate_js("hideConfirmation()")
        except Exception:
            pass

    def resolve_confirmation(self, confirmation_id: str, approved: bool) -> dict:
        with self._confirmation_lock:
            info = self._pending_confirmations.get(confirmation_id)
            if info:
                info["approved"] = approved
                info["event"].set()
                return {"success": True, "approved": approved}
        return {"success": False, "message": "No matching confirmation pending"}

    def resolve_active_confirmation(self, approved: bool) -> bool:
        """Resolves whatever confirmation is currently pending (e.g. triggered via voice recognition)."""
        with self._confirmation_lock:
            if not self._pending_confirmations:
                return False
            for req_id, info in list(self._pending_confirmations.items()):
                info["approved"] = approved
                info["event"].set()
                self.hide_confirmation()
                return True
        return False

    def has_pending_confirmation(self) -> bool:
        with self._confirmation_lock:
            return bool(self._pending_confirmations)

    def wait_for_confirmation(
        self,
        command: str,
        shell: str = "cmd",
        risk_level: str = "HIGH",
        reason: str = "",
        timeout_seconds: int = 20,
    ) -> bool:
        """Shows the confirmation dialog in the HUD and blocks until approved, denied, or timed out."""
        import uuid
        req_id = f"conf_{uuid.uuid4().hex[:8]}"
        done_event = threading.Event()
        info = {
            "id": req_id,
            "command": command,
            "shell": shell,
            "risk_level": risk_level,
            "reason": reason,
            "approved": False,
            "event": done_event,
        }

        with self._confirmation_lock:
            self._pending_confirmations[req_id] = info

        self.show_confirmation(req_id, command, shell, risk_level, reason, timeout_seconds)

        try:
            done_event.wait(timeout=float(timeout_seconds) + 0.5)
            self.hide_confirmation()
            return info["approved"]
        finally:
            with self._confirmation_lock:
                self._pending_confirmations.pop(req_id, None)


    def set_state(self, state: State) -> None:
        self.current_state = state
        try:
            self._window.evaluate_js(f"setState('{state}')")
        except Exception:
            pass

    def set_level(self, level: float) -> None:
        try:
            self._window.evaluate_js(f"setLevel({level})")
        except Exception:
            pass

    def add_message(
        self,
        who: Literal["you", "jarvis"],
        text: str,
        tone: Literal["positive", "negative"] = "positive",
    ) -> None:
        try:
            escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "<br>")
            self._window.evaluate_js(f"addMessage('{who}', '{escaped}', '{tone}')")
        except Exception:
            pass

    def clear_log(self) -> None:
        try:
            self._window.evaluate_js("clearLog()")
        except Exception:
            pass
