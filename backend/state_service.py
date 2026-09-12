"""
Orchestrates pipeline, features, rules, ML fusion, smoothing, CSV logging, and status.
"""
from __future__ import annotations

import csv
import logging
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
from backend.paths import logs_dir, model_path, scaler_path
from backend.pattern_detector import PatternDetector
from backend.pipeline import DataPipeline
from backend.prediction_smoother import PredictionSmoother
from backend.rules import RulesEngine
from backend.session_manager import (
    PHASE_CALIBRATING,
    PHASE_IDLE,
    SessionManager,
)
from backend.state_machine import StateMachine
from backend.trend_predictor import TrendPrediction, TrendPredictor

LOG = logging.getLogger(__name__)


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
        new_file = not self._csv_path.is_file()
        self._csv_file = open(self._csv_path, "a", newline="", encoding="utf-8")
        fields = [
            "timestamp_iso",
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
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=fields)
        if new_file:
            self._csv_writer.writeheader()
            self._csv_file.flush()
        LOG.info("CSV log: %s", self._csv_path)

    def log_exercise_event(self, event: str) -> None:
        with self._lock:
            if self._csv_writer is None:
                return
            self._csv_writer.writerow(
                {
                    "timestamp_iso": datetime.utcnow().isoformat() + "Z",
                    "hr": self._snapshot.hr if self._snapshot.hr is not None else "",
                    "gsr": self._snapshot.gsr if self._snapshot.gsr is not None else "",
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
                self._maybe_log_csv(sample, None, None, None, None, None, None, None)
                return
            hr, gsr = out
            now = time.time()
            self.baseline.update_with_sample(now, hr, gsr)
            if self.baseline.is_ready() and self.sessions.phase == PHASE_CALIBRATING:
                self.sessions.mark_calibrated(now)
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
            "calibration": self._calibration_dict(now),   # returns None until P2
            "live": None,                                  # filled in P3
        }

    def _calibration_dict(self, now: float) -> Optional[Dict[str, Any]]:
        """Calibration telemetry. Implemented in P2; None until then."""
        # NOTE(plan): P1 stub — P2 replaces this with real telemetry.
        return None

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
            return {"ok": True, "session_id": st.id, "phase": st.phase, "label": st.label}

    def end_session(self) -> Dict[str, Any]:
        """End the active session. Returns {"ok": bool, ...}."""
        with self._lock:
            st = self.sessions.end(time.time())
            if st is None:
                return {"ok": False, "error": "no_active_session"}
            # P3 attaches report finalization here.
            return {"ok": True, "session_id": st.id, "reliability": None}

    def restart_calibration(self) -> Dict[str, Any]:
        """Restart baseline measurement without ending the session."""
        with self._lock:
            if not self.sessions.restart_calibration(time.time()):
                return {"ok": False, "error": "not_calibrating"}
            self.pipeline.reset()
            self.baseline.reset()
            self._snapshot.calibrated = False
            self._snapshot.features = None
            return {"ok": True, "session_id": self.sessions.state.id,
                    "attempts": self.sessions.state.calibration_attempts}
