"""Flask application factory: REST + optional SSE stream + static frontend."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.paths import logs_dir, project_root, sessions_dir
from backend.report_render import render_html

LOG = logging.getLogger(__name__)

# Session ids are validated before any filesystem access. Anything else is a 404,
# so a crafted id can never escape data/sessions/ (PLAN.md edge case 26).
_SESSION_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
_SESSIONS_LIST_LIMIT = 50

if TYPE_CHECKING:
    from backend.state_service import AnxietyStateService


def _read_report_file(session_id: str) -> Optional[Dict[str, Any]]:
    """Load a stored report: the final file, else a checkpoint marked interrupted."""
    final = sessions_dir() / (session_id + ".json")
    if final.is_file():
        try:
            with open(final, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError) as e:
            LOG.debug("unreadable report %s: %s", final.name, e)
    partial = sessions_dir() / (session_id + ".partial.json")
    if partial.is_file():
        try:
            with open(partial, "r", encoding="utf-8") as fh:
                report = json.load(fh)
            # A checkpoint with no final file means the backend never closed this
            # session out; say so rather than presenting it as a finished report.
            report["status"] = "interrupted"
            return report
        except (OSError, ValueError) as e:
            LOG.debug("unreadable checkpoint %s: %s", partial.name, e)
    return None


def _lookup_report(service: "AnxietyStateService", session_id: str) -> Optional[Dict[str, Any]]:
    """The live partial for the running session, otherwise the stored report."""
    if session_id == service.current_session_id():
        live = service.build_partial_report()
        if live is not None:
            return live
    return _read_report_file(session_id)


def _session_list_items() -> list:
    """Newest-first summaries of stored reports.

    NOTE(plan): filenames start with a sortable local timestamp, so the newest
    candidates are chosen before any file is opened. The listing therefore costs
    a bounded number of reads no matter how many sessions accumulate.
    """
    try:
        paths = [q for q in sessions_dir().glob("*.json")
                 if not q.name.endswith(".partial.json")]
    except OSError as e:
        LOG.debug("sessions dir unreadable: %s", e)
        return []
    paths.sort(key=lambda q: q.name, reverse=True)
    items = []
    for path in paths[:_SESSIONS_LIST_LIMIT]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
        except (OSError, ValueError) as e:
            LOG.debug("skipping unreadable report %s: %s", path.name, e)
            continue
        identity = report.get("identity") or {}
        quality = report.get("quality") or {}
        states = report.get("states") or {}
        peak_state = None
        if states.get("seconds"):
            for candidate in ("ANXIETY", "STRESS", "RECOVERY", "CALM"):
                if states["seconds"].get(candidate):
                    peak_state = candidate
                    break
        items.append({
            "id": identity.get("id") or path.stem,
            "label": identity.get("label"),
            "started_at_iso": identity.get("started_at_iso"),
            "duration_s": identity.get("total_duration_s"),
            "reliability": quality.get("reliability"),
            "peak_state": peak_state,
            "episode_count": report.get("episode_count"),
            "status": report.get("status"),
        })
    items.sort(key=lambda item: item.get("started_at_iso") or "", reverse=True)
    return items


def _session_csv(session_id: str) -> str:
    """The raw log rows belonging to one session, header preserved."""
    path = logs_dir() / "physio_log.csv"
    buffer = io.StringIO()
    if not path.is_file():
        return ""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            if row.get("session_id") == session_id:
                writer.writerow(row)
    return buffer.getvalue()


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

    @app.route("/sessions", methods=["GET"])
    def sessions_list():
        return jsonify(_session_list_items())

    @app.route("/session/<sid>/report", methods=["GET"])
    def session_report(sid: str):
        if not _SESSION_ID_RE.match(sid):
            return jsonify({"error": "not_found"}), 404
        report = _lookup_report(service, sid)
        if report is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(report)

    @app.route("/session/<sid>/report.html", methods=["GET"])
    def session_report_html(sid: str):
        if not _SESSION_ID_RE.match(sid):
            return jsonify({"error": "not_found"}), 404
        report = _lookup_report(service, sid)
        if report is None:
            return jsonify({"error": "not_found"}), 404
        return Response(
            render_html(report),
            mimetype="text/html",
            headers={"Content-Disposition": 'attachment; filename="saarthi-%s.html"' % sid},
        )

    @app.route("/session/<sid>/report.csv", methods=["GET"])
    def session_report_csv(sid: str):
        if not _SESSION_ID_RE.match(sid):
            return jsonify({"error": "not_found"}), 404
        return Response(
            _session_csv(sid),
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="saarthi-%s.csv"' % sid},
        )

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
