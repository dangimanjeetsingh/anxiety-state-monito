"""
Orchestrates pipeline, features, rules, ML fusion, smoothing, CSV logging, and status.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from backend.bt_reader import BluetoothReader, Sample
from backend.config import AppConfig
from backend.features import BaselineTracker, compute_features
from backend.fusion import FusionEngine
from backend.ml_predictor import MlPredictor
from backend.alert_system import AlertSystem
from backend.paths import logs_dir, model_path, scaler_path, sessions_dir
from backend.pattern_detector import PatternDetector
from backend.pipeline import DataPipeline
from backend.prediction_smoother import PredictionSmoother
from backend.rules import RulesEngine
from backend.session_recorder import SessionRecorder
from backend.session_manager import (
    PHASE_CALIBRATING,
    PHASE_ENDED,
    PHASE_IDLE,
    SessionManager,
)
from backend.state_machine import StateMachine
from backend.trend_predictor import TrendPrediction, TrendPredictor

LOG = logging.getLogger(__name__)

# CSV schema v2 (PLAN.md section 3.7). Changing this list requires a log rotation,
# which _rotate_csv_if_stale() performs on startup.
CSV_FIELDNAMES = [
    "timestamp_iso",
    "session_id",
    "session_phase",
    "hr",
    "gsr",
    "raw_line",
    "rule_state",
    "ml_state",
    "fused_state",
    "final_state",
    "connection",
    "exercise_event",
]


@dataclass
class DashboardSnapshot:
    hr: Optional[float]
    gsr: Optional[float]
    state: str
    rule_state: str
    ml_state: Optional[str]
    fused_state: str
    fusion_source: str
    connection: str
    connection_detail: Optional[str]
    sensor_warning: Optional[str]       # e.g. "Place finger on sensor"
    baseline_hr: Optional[float]
    baseline_gsr: Optional[float]
    features: Optional[Dict[str, float]]
    window_samples: int
    calibrated: bool
    pattern: Optional[str]
    alert: Optional[str]
    prediction: Optional[Dict[str, Any]] = None
    session: Optional[Dict[str, Any]] = None


class AnxietyStateService:
    """Thread-safe service used by Flask handlers and background reader."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._lock = threading.Lock()
        self.pipeline = DataPipeline(config.pipeline)
        self.baseline = BaselineTracker(
            config.baseline.calibration_seconds,
            config.baseline.fixed_hr,
            config.baseline.fixed_gsr,
        )
        self.rules = RulesEngine(config.thresholds)
        self._ml = MlPredictor(model_path(), scaler_path())
        self.fusion = FusionEngine(config.ml, self._ml)
        self.smoother = PredictionSmoother(
            config.smoothing.history_size,
            config.smoothing.hysteresis_confirm,
        )
        self.fsm = StateMachine()
        self.pattern_detector = PatternDetector()
        self.alert_system = AlertSystem()
        self.trend_predictor = TrendPredictor(config)
        self.sessions = SessionManager()
        self._recorder: Optional[SessionRecorder] = None
        self._last_live_summary: Optional[Dict[str, Any]] = None
        self._last_checkpoint_ts = 0.0
        self._prev_rule_state: Optional[str] = None
        self._latest_hr: Optional[float] = None
        self._latest_gsr: Optional[float] = None
        self._snapshot = DashboardSnapshot(
            hr=None,
            gsr=None,
            state="CALM",
            rule_state="CALM",
            ml_state=None,
            fused_state="CALM",
            fusion_source="rules",
            connection="starting",
            connection_detail=None,
            sensor_warning=None,
            baseline_hr=None,
            baseline_gsr=None,
            features=None,
            window_samples=0,
            calibrated=False,
            pattern=None,
            alert=None,
            prediction={"active": False},
        )
        self._csv_file: Any = None
        self._csv_writer: Any = None
        self._last_csv_ts = 0.0
        self._reader: Optional[BluetoothReader] = None
        self._csv_path = logs_dir() / "physio_log.csv"

    def start_reader(self) -> None:
        if self._reader:
            return
        self._open_csv()
        self._reader = BluetoothReader(
            self._cfg.serial,
            on_sample=self._on_sample,
            on_status=self._on_status,
            mock_calibration_seconds=self._cfg.baseline.calibration_seconds,
        )
        self._reader.start()
        LOG.info("Bluetooth reader thread started (mock=%s)", self._cfg.serial.use_mock)
        if self._cfg.session.autostart:
            self.start_session(label=None)

    def stop_reader(self) -> None:
        if self._reader:
            self._reader.stop()
            self._reader = None
        self._close_csv()

    def _open_csv(self) -> None:
        self._csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_csv_if_stale()
        new_file = not self._csv_path.is_file()
        self._csv_file = open(self._csv_path, "a", newline="", encoding="utf-8")
        fields = list(CSV_FIELDNAMES)
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=fields)
        if new_file:
            self._csv_writer.writeheader()
            self._csv_file.flush()
        LOG.info("CSV log: %s", self._csv_path)

    def _csv_session_id(self) -> str:
        """Session id for a CSV row: blank outside a recording phase (PLAN.md section 3.7)."""
        st = self.sessions.state
        return st.id if (st.recording and st.id) else ""

    def _rotate_csv_if_stale(self) -> None:
        """Retire a log whose header predates the current schema (PLAN.md section 3.7).

        Appending new columns to an existing file would silently misalign every
        earlier row, so the old log is renamed and a fresh one is started.
        """
        if not self._csv_path.is_file():
            return
        expected = ",".join(CSV_FIELDNAMES)
        try:
            with open(self._csv_path, "r", encoding="utf-8") as fh:
                first_line = fh.readline().strip()
        except OSError as e:
            LOG.warning("Could not read CSV header, leaving log untouched: %s", e)
            return
        if first_line == expected:
            return
        target = self._csv_path.with_name("physio_log.pre_sessions.csv")
        suffix = 0
        while target.exists():
            suffix += 1
            target = self._csv_path.with_name("physio_log.pre_sessions-%d.csv" % suffix)
        try:
            self._csv_path.rename(target)
            LOG.info("Rotated pre-session CSV log to %s", target.name)
        except OSError as e:
            LOG.warning("Could not rotate CSV log: %s", e)

    def log_exercise_event(self, event: str) -> None:
        with self._lock:
            if self._csv_writer is None:
                return
            self._csv_writer.writerow(
                {
                    "timestamp_iso": datetime.utcnow().isoformat() + "Z",
                    "hr": self._snapshot.hr if self._snapshot.hr is not None else "",
                    "gsr": self._snapshot.gsr if self._snapshot.gsr is not None else "",
                    "session_id": self._csv_session_id(),
                    "session_phase": self.sessions.phase,
                    "raw_line": f"EXERCISE_{event.upper()}",
                    "rule_state": self._snapshot.rule_state or "",
                    "ml_state": self._snapshot.ml_state or "",
                    "fused_state": self._snapshot.fused_state or "",
                    "final_state": self._snapshot.state or "",
                    "connection": self._snapshot.connection,
                    "exercise_event": event,
                }
            )
            self._csv_file.flush()

    def _close_csv(self) -> None:
        if self._csv_file:
            try:
                self._csv_file.close()
            except Exception as e:
                LOG.debug("csv close: %s", e)
            self._csv_file = None
            self._csv_writer = None

    def _on_status(self, status: str, detail: Optional[str]) -> None:
        with self._lock:
            if status == "sensor_warning":
                # Keep existing connection state; only update the warning message
                self._snapshot.sensor_warning = detail
            elif status == "no_data":
                self._snapshot.connection = "no_data"
                self._snapshot.connection_detail = detail
                self._snapshot.sensor_warning = None
            elif status == "connected":
                self._snapshot.connection = status
                if detail is not None:          # preserve port info on reconnect
                    self._snapshot.connection_detail = detail
                self._snapshot.sensor_warning = None  # clear warning on good data
            else:
                self._snapshot.connection = status
                self._snapshot.connection_detail = detail
                self._snapshot.sensor_warning = None
        LOG.info("Connection status: %s %s", status, detail or "")

    def _on_sample(self, sample: Sample) -> None:
        with self._lock:
            # Always update latest raw values immediately (before any smoothing)
            self._snapshot.hr = round(sample.hr, 1)
            self._snapshot.gsr = round(sample.gsr, 1)
            # Session gating: outside CALIBRATING/MONITORING we ingest and log raw
            # values (so the dashboard can act as a sensor check) but run no
            # evaluation and keep no session state.
            if not self.sessions.state.recording:
                self._maybe_log_csv(sample, None, None, None, None, None, None,
                                    self._snapshot.connection)
                return
            out = self.pipeline.push(sample.hr, sample.gsr)
            if out is None:
                if self._recorder is not None and self.sessions.state.evaluating:
                    self._recorder.note_rejected_sample()
                self._maybe_log_csv(sample, None, None, None, None, None, None, None)
                return
            hr, gsr = out
            now = time.time()
            self.baseline.update_with_sample(now, hr, gsr)
            if self.baseline.is_ready() and self.sessions.phase == PHASE_CALIBRATING:
                self.sessions.mark_calibrated(now)
                if self._recorder is not None:
                    self._recorder.note_calibrated(
                        now,
                        self.baseline.baseline_hr,
                        self.baseline.baseline_gsr,
                        self.baseline.calibration_method,
                        self.baseline.calibration_locked_after_s(),
                        self.sessions.state.calibration_attempts,
                    )
            self._latest_hr = hr
            self._latest_gsr = gsr
            window = self.pipeline.window_points()
            fv = compute_features(
                window, self.baseline, now,
                stress_w_hr=self._cfg.baseline.stress_w_hr,
                stress_w_gsr=self._cfg.baseline.stress_w_gsr,
            )
            if fv is None:
                self._snapshot.hr = hr
                self._snapshot.gsr = gsr
                self._snapshot.window_samples = len(window)
                self._snapshot.baseline_hr = self.baseline.baseline_hr
                self._snapshot.baseline_gsr = self.baseline.baseline_gsr
                # Use the authoritative is_calibrated flag (set once after
                # the calibration window closes, not just when values appear).
                self._snapshot.calibrated = self.baseline.is_ready()
                # NOTE(plan): only count rejects once monitoring has begun. Every
                # sample during CALIBRATING takes this path by design, and counting
                # those would report a healthy session as mostly-rejected data.
                if self._recorder is not None and self.sessions.state.evaluating:
                    self._recorder.note_rejected_sample()
                self._maybe_log_csv(sample, hr, gsr, None, None, None, None, None)
                return
            try:
                rule_state = self.rules.classify(fv, self._prev_rule_state)
                self._prev_rule_state = rule_state
                ml_pred = self._ml.predict(fv)
                ml_state = ml_pred.label if ml_pred else None
                fused = self.fusion.fuse(rule_state, ml_pred, feature_confidence=fv.confidence)
                smoothed_state = self.smoother.push(fused.state)
                final_state = self.fsm.update(
                    input_state=smoothed_state,
                    features=fv,
                    now_t=now,
                )
                pattern_type = self.pattern_detector.update(fv, now)
                alert_level = self.alert_system.update(
                    state=final_state,
                    pattern=pattern_type,
                    confidence=fv.confidence,
                    now_t=now,
                )
                prediction_res = self.trend_predictor.update(
                    fv=fv,
                    current_state=final_state,
                    calibrated=self.baseline.is_ready(),
                    input_state=smoothed_state,
                )
            except Exception as e:
                LOG.error("Evaluation pipeline crashed: %s", e)
                # Fallback to pure rules engine if fsm/ml corrupt
                rule_state = self.rules.classify(fv, self._prev_rule_state)
                ml_state = None
                fused = None
                final_state = rule_state
                pattern_type = None
                alert_level = None
                prediction_res = TrendPrediction(active=False)
            feat_map = {
                "mean_hr": fv.mean_hr,
                "std_hr": fv.std_hr,
                "hr_trend": fv.hr_trend,
                "mean_gsr": fv.mean_gsr,
                "std_gsr": fv.std_gsr,
                "gsr_trend": fv.gsr_trend,
                "delta_hr": fv.delta_hr,
                "delta_gsr": fv.delta_gsr,
                "stress_index": fv.stress_index,
                "confidence": fv.confidence,
            }
            self._snapshot = DashboardSnapshot(
                hr=hr,
                gsr=gsr,
                state=final_state,
                rule_state=rule_state,
                ml_state=ml_state,
                fused_state=fused.state if fused else rule_state,
                fusion_source=fused.source if fused else "rules",
                connection=self._snapshot.connection,
                connection_detail=self._snapshot.connection_detail,
                sensor_warning=None,   # cleared on every good sample
                baseline_hr=self.baseline.baseline_hr,
                baseline_gsr=self.baseline.baseline_gsr,
                features=feat_map,
                window_samples=len(window),
                calibrated=self.baseline.is_ready(),
                pattern=pattern_type,
                alert=alert_level,
                prediction=prediction_res.to_dict(),
            )
            self._maybe_log_csv(
                sample,
                hr,
                gsr,
                rule_state,
                ml_state,
                fused.state if fused else rule_state,
                final_state,
                self._snapshot.connection,
            )
            # Recording is deliberately outside the evaluation try/except above:
            # a recorder fault must never affect live monitoring (PLAN.md F-O).
            if self._recorder is not None:
                try:
                    self._recorder.observe(
                        now=now,
                        phase=self.sessions.phase,
                        hr=hr, gsr=gsr,
                        state=final_state, rule_state=rule_state, ml_state=ml_state,
                        fused_state=self._snapshot.fused_state,
                        fusion_source=self._snapshot.fusion_source,
                        pattern=pattern_type, alert=alert_level,
                        features=feat_map, prediction=self._snapshot.prediction,
                        connection=self._snapshot.connection,
                    )
                except Exception as e:
                    LOG.debug("recorder observe: %s", e)
                self._maybe_checkpoint(now)

    def _maybe_log_csv(
        self,
        sample: Sample,
        hr: Optional[float],
        gsr: Optional[float],
        rule_state: Optional[str],
        ml_state: Optional[str],
        fused: Optional[str],
        final_state: Optional[str],
        connection: str,
    ) -> None:
        if self._csv_writer is None:
            return
        now = time.time()
        if now - self._last_csv_ts < self._cfg.csv_log_interval_s:
            return
        self._last_csv_ts = now
        self._csv_writer.writerow(
            {
                "timestamp_iso": datetime.utcnow().isoformat() + "Z",
                "session_id": self._csv_session_id(),
                "session_phase": self.sessions.phase,
                "hr": hr if hr is not None else "",
                "gsr": gsr if gsr is not None else "",
                "raw_line": sample.raw_line,
                "rule_state": rule_state or "",
                "ml_state": ml_state or "",
                "fused_state": fused or "",
                "final_state": final_state or "",
                "connection": connection,
                "exercise_event": "",
            }
        )
        self._csv_file.flush()

    def _maybe_checkpoint(self, now: float) -> None:
        """Write a .partial.json checkpoint at most every checkpoint_interval_s.

        NOTE(plan): the write happens under the service lock. The file is small
        (<100 KB) and written via tmp+replace, so the added hold time is one
        buffered write per interval.
        """
        if self._recorder is None:
            return
        if now - self._last_checkpoint_ts < self._cfg.session.checkpoint_interval_s:
            return
        self._last_checkpoint_ts = now
        try:
            report = self._recorder.build_report(
                now,
                status="partial",
                end_reason=None,
                terminal_state=self._snapshot.state,
                terminal_phase=self.sessions.phase,
            )
            self._write_json_atomic(
                sessions_dir() / (self._recorder.session_id + ".partial.json"), report
            )
        except Exception as e:
            LOG.debug("session checkpoint: %s", e)

    @staticmethod
    def _write_json_atomic(path, payload: Dict[str, Any]) -> None:
        """Write JSON via a tmp file + os.replace so readers never see a partial write."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)

    def get_snapshot(self) -> DashboardSnapshot:
        with self._lock:
            return self._snapshot

    def to_json_dict(self) -> Dict[str, Any]:
        with self._lock:
            s = self._snapshot
            session_block = self._session_dict(time.time())
        return {
            "server_time": time.time(),
            "hr": round(s.hr, 1) if s.hr is not None else None,
            "gsr": round(s.gsr, 1) if s.gsr is not None else None,
            "state": s.state,
            "rule_state": s.rule_state,
            "ml_state": s.ml_state,
            "fused_state": s.fused_state,
            "fusion_source": s.fusion_source,
            "connection": s.connection,
            "connection_detail": s.connection_detail,
            "sensor_warning": s.sensor_warning,
            "baseline_hr": s.baseline_hr,
            "baseline_gsr": s.baseline_gsr,
            "features": s.features,
            "window_samples": s.window_samples,
            "calibrated": s.calibrated,
            "pattern": s.pattern,
            "alert": s.alert,
            "prediction": s.prediction if s.prediction is not None else {"active": False},
            "session": session_block,
        }

    def _session_dict(self, now: float) -> Dict[str, Any]:
        """Build the `session` block. Caller must hold the lock."""
        st = self.sessions.state
        if st.phase == PHASE_IDLE:
            return {
                "phase": PHASE_IDLE, "id": None, "label": None, "started_at": None,
                "elapsed_s": 0.0, "monitored_s": 0.0,
                "recording": False, "evaluating": False,
                "calibration": None, "live": None,
            }
        return {
            "phase": st.phase,
            "id": st.id,
            "label": st.label,
            "started_at": st.started_at,
            "elapsed_s": round(st.elapsed_s(now), 1),
            "monitored_s": round(st.monitored_s(now), 1),
            "recording": st.recording,
            "evaluating": st.evaluating,
            "calibration": self._calibration_dict(now),
            "live": self._live_dict(now),
        }

    def _live_dict(self, now: float) -> Optional[Dict[str, Any]]:
        """Running session summary; the last one survives into ENDED for the UI."""
        if self._recorder is not None:
            self._last_live_summary = self._recorder.live_summary(now)
        return self._last_live_summary

    def _calibration_dict(self, now: float) -> Optional[Dict[str, Any]]:
        """Calibration telemetry for the `session` block. Caller holds the lock."""
        st = self.sessions.state
        if st.phase == PHASE_IDLE:
            return None
        b = self.baseline
        target = b.calibration_target_s
        elapsed = b.calibration_elapsed_s(now)
        conn = (self._snapshot.connection or "").lower()
        paused = st.phase == PHASE_CALIBRATING and conn not in ("connected", "mock")
        stall_after = target * self._cfg.session.calibration_stall_factor
        stalled = (
            st.phase == PHASE_CALIBRATING
            and not paused
            and elapsed > stall_after
        )
        return {
            "method": b.calibration_method,
            "progress": round(b.calibration_progress(), 3),
            "elapsed_s": round(elapsed, 1),
            "target_s": target,
            "stable": bool(b.calibration_stable),
            "stalled": bool(stalled),
            "paused": bool(paused),
            "attempts": st.calibration_attempts,
        }

    def reset_session(self) -> None:
        with self._lock:
            self._reset_session_locked()

    def _reset_session_locked(self) -> None:
        """Reset every per-session subsystem. Caller must hold the lock."""
        self.pipeline.reset()
        self.baseline.reset()
        self.smoother.reset()
        self.fsm = StateMachine()
        self.pattern_detector = PatternDetector()
        self.alert_system = AlertSystem()
        self.trend_predictor.reset()
        self._prev_rule_state = None
        self._latest_hr = None
        self._latest_gsr = None

    def start_session(self, label: Optional[str] = None) -> Dict[str, Any]:
        """Start a fresh session. Returns {"ok": bool, ...}."""
        with self._lock:
            if self.sessions.state.active:
                return {"ok": False, "error": "session_active",
                        "session_id": self.sessions.state.id}
            now = time.time()
            self._reset_session_locked()
            st = self.sessions.start(label, now)
            self._snapshot.state = "CALM"
            self._snapshot.calibrated = False
            self._snapshot.features = None
            # NOTE(plan): also clear the displayed baseline so the previous
            # person's values are never shown against a new session.
            self._snapshot.baseline_hr = None
            self._snapshot.baseline_gsr = None
            self._recorder = SessionRecorder(
                session_id=st.id,
                label=st.label,
                started_at=now,
                target_calibration_s=self.baseline.calibration_target_s,
            )
            self._last_live_summary = None
            self._last_checkpoint_ts = now
            return {"ok": True, "session_id": st.id, "phase": st.phase, "label": st.label}

    def end_session(self) -> Dict[str, Any]:
        """End the active session, write its report, and return the reliability grade."""
        with self._lock:
            now = time.time()
            st = self.sessions.end(now)
            if st is None:
                return {"ok": False, "error": "no_active_session"}
            recorder = self._recorder
            self._recorder = None
            report = None
            if recorder is not None:
                try:
                    report = recorder.build_report(
                        now,
                        status="final",
                        end_reason=st.end_reason,
                        terminal_state=self._snapshot.state,
                        terminal_phase=PHASE_ENDED,
                    )
                    self._last_live_summary = recorder.live_summary(now)
                except Exception as e:
                    LOG.error("Could not build session report for %s: %s", st.id, e)
            session_id = st.id

        # File I/O outside the lock: the live pipeline must not wait on the disk.
        reliability = None
        if report is not None:
            reliability = report["quality"]["reliability"]
            try:
                self._write_json_atomic(sessions_dir() / (session_id + ".json"), report)
            except Exception as e:
                LOG.error("Could not write session report %s: %s", session_id, e)
            try:
                (sessions_dir() / (session_id + ".partial.json")).unlink()
            except OSError:
                pass
        return {"ok": True, "session_id": session_id, "reliability": reliability}

    def restart_calibration(self) -> Dict[str, Any]:
        """Restart baseline measurement without ending the session."""
        with self._lock:
            if not self.sessions.restart_calibration(time.time()):
                return {"ok": False, "error": "not_calibrating"}
            self.pipeline.reset()
            self.baseline.reset()
            self._snapshot.calibrated = False
            self._snapshot.features = None
            if self._recorder is not None:
                self._recorder.note_calibration_restart()
            return {"ok": True, "session_id": self.sessions.state.id,
                    "attempts": self.sessions.state.calibration_attempts}
