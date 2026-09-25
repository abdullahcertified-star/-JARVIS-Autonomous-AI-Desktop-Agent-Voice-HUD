"""JARVIS Desktop Automation Server.

Entry point only: builds/loads the application database, prints the startup
banner, and exposes the single POST /execute endpoint. All automation logic
lives in dispatcher.py + actions/*.
"""

from __future__ import annotations

import sys

from pathlib import Path
from flask import Flask, jsonify, request, send_file, send_from_directory

import config
from dispatcher import dispatch
from search.app_search import get_index

# Windows consoles often default to a legacy codepage (e.g. cp1252) that
# can't encode the checkmark in the startup banner -- force UTF-8 for
# stdio so the banner never crashes the process on startup.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# A handful of well-known app names highlighted in the startup banner when
# present -- purely cosmetic, has no effect on discovery or launching.
_BANNER_HIGHLIGHTS = (
    "chrome", "edge", "visual studio code", "discord", "docker",
    "packet tracer", "slack", "spotify", "steam", "obs studio",
    "microsoft teams", "vlc",
)


def _print_banner(index) -> None:
    shown: set[str] = set()
    for highlight in _BANNER_HIGHLIGHTS:
        match = index.find(highlight)
        if match and match.name not in shown:
            print(f"  ✓ {match.name}")
            shown.add(match.name)
        if len(shown) >= 8:
            break

    print(f"Found {len(index)} applications.")
    print("Application database loaded.")
    print("JARVIS Desktop API Ready.\n")


def create_app() -> Flask:
    app = Flask(__name__)

    index = get_index()
    _print_banner(index)

    @app.route("/execute", methods=["POST"])
    def execute():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "message": "No JSON received"}), 400

        result = dispatch(data)
        # Always 200 here: "success" inside the JSON body is the contract the
        # caller checks. Non-2xx is reserved for a malformed request,
        # not a business-logic failure like "app not found".
        return jsonify(result)

    @app.route("/chat", methods=["POST"])
    def chat():
        data = request.get_json(silent=True) or {}
        message = data.get("message") or data.get("text") or data.get("prompt")
        if not message:
            return jsonify({"success": False, "message": "No message provided (expected 'message', 'text', or 'prompt')"}), 400

        try:
            from agent import get_agent
            reply = get_agent().chat(str(message))
            return jsonify({"success": True, "reply": reply})
        except Exception as exc:
            return jsonify({"success": False, "message": f"Agent error: {exc}"}), 500

    @app.route("/chat/reset", methods=["POST"])
    def reset_chat():
        try:
            from agent import get_agent
            get_agent().reset_chat()
            return jsonify({"success": True, "message": "Chat memory reset."})
        except Exception as exc:
            return jsonify({"success": False, "message": f"Reset failed: {exc}"}), 500

    @app.route("/", methods=["GET"])
    def health():
        return jsonify({
            "status": "JARVIS Desktop API Running",
            "applications_indexed": len(index),
            "agent_configured": bool(config.GEMINI_API_KEY),
            "dashboard_url": "http://127.0.0.1:5000/dashboard",
        })

    @app.route("/dashboard", methods=["GET"])
    @app.route("/dashboard/", methods=["GET"])
    def dashboard_view():
        out_dir = Path(__file__).parent / "voice" / "web" / "out"
        return send_file(out_dir / "index.html")

    @app.route("/_next/<path:filename>", methods=["GET"])
    def next_assets(filename):
        out_dir = Path(__file__).parent / "voice" / "web" / "out" / "_next"
        return send_from_directory(out_dir, filename)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
