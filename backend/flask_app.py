"""Flask application factory: REST + optional SSE stream + static frontend."""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.paths import project_root

if TYPE_CHECKING:
    from backend.state_service import AnxietyStateService


def create_app(service: "AnxietyStateService") -> Flask:
    root = project_root()
    frontend = root / "frontend"
    app = Flask(__name__, static_folder=str(frontend), static_url_path="")
    CORS(app)

    @app.route("/")
    def index():
        return send_from_directory(frontend, "index.html")

    @app.route("/data", methods=["GET"])
    def data():
        resp = jsonify(service.to_json_dict())
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @app.route("/session/exercise", methods=["POST"])
    def session_exercise():
        payload = request.get_json(silent=True) or {}
        event = payload.get("event", "unknown")
        service.log_exercise_event(str(event))
        return jsonify({"status": "ok", "event": event})

    @app.route("/session/start", methods=["POST"])
    def session_start():
        payload = request.get_json(silent=True) or {}
        res = service.start_session(label=payload.get("label"))
        if not res.get("ok"):
            return jsonify({"error": res.get("error"),
                            "session_id": res.get("session_id")}), 409
        return jsonify({"session_id": res["session_id"], "phase": res["phase"],
                        "label": res["label"]}), 201

    @app.route("/session/end", methods=["POST"])
    def session_end():
        res = service.end_session()
        if not res.get("ok"):
            return jsonify({"error": res.get("error")}), 409
        return jsonify({
            "session_id": res["session_id"],
            "report_url": "/session/" + res["session_id"] + "/report",
            "reliability": res.get("reliability"),
        })

    @app.route("/session/calibration/restart", methods=["POST"])
    def session_calibration_restart():
        res = service.restart_calibration()
        if not res.get("ok"):
            return jsonify({"error": res.get("error")}), 409
        return jsonify({"session_id": res["session_id"], "attempts": res["attempts"]})

    @app.route("/session/intervention", methods=["POST"])
    def session_intervention():
        payload = request.get_json(silent=True) or {}
        event = str(payload.get("event", "")).lower()
        if event not in ("start", "stop"):
            return jsonify({"error": "invalid_event"}), 400
        res = service.log_intervention(
            event,
            technique=str(payload.get("technique") or "box_4_4_4_4"),
            planned_duration_s=payload.get("planned_duration_s"),
            cycles_completed=payload.get("cycles_completed"),
        )
        if not res.get("ok"):
            return jsonify({"error": res.get("error")}), 409
        return jsonify({"status": "ok", "index": res.get("index")})

    @app.route("/stream")
    def stream():
        """Server-Sent Events: one JSON payload per second."""

        def event_stream():
            while True:
                payload = json.dumps(service.to_json_dict())
                yield f"data: {payload}\n\n"
                time.sleep(1.0)

        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app
