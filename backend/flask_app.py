"""Flask application factory: REST + optional SSE stream + static frontend."""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from flask import Flask, Response, jsonify, send_from_directory
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
