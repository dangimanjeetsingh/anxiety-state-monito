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
from backend.state_machine import StateMachine

LOG = logging.getLogger(__name__)


@dataclass
class DashboardSnapshot:
    hr: Optional[float]
    gsr: Optional[float]
    state: str
    rule_state: str
    ml_state: Optional[str]
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
        self._prev_rule_state: Optional[str] = None
        self._latest_hr: Optional[float] = None
        self._latest_gsr: Optional[float] = None
        self._snapshot = DashboardSnapshot(
            hr=None,
            gsr=None,
            state="CALM",
            rule_state="CALM",
            ml_state=None,
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
        )
        self._reader.start()
        LOG.info("Bluetooth reader thread started (mock=%s)", self._cfg.serial.use_mock)

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
        ]
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=fields)
        if new_file:
            self._csv_writer.writeheader()
            self._csv_file.flush()
        LOG.info("CSV log: %s", self._csv_path)

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
            out = self.pipeline.push(sample.hr, sample.gsr)
            if out is None:
                self._maybe_log_csv(sample, None, None, None, None, None, None, None)
                return
            hr, gsr = out
            print(f"HR: {hr}, GSR: {gsr}")
            now = time.time()
            self.baseline.update_with_sample(now, hr, gsr)
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
            except Exception as e:
                LOG.error("Evaluation pipeline crashed: %s", e)
                # Fallback to pure rules engine if fsm/ml corrupt
                rule_state = self.rules.classify(fv, self._prev_rule_state)
                ml_state = None
                fused = None
                final_state = rule_state
                pattern_type = None
                alert_level = None
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
            }
        )
        self._csv_file.flush()

    def get_snapshot(self) -> DashboardSnapshot:
        with self._lock:
            return self._snapshot

    def to_json_dict(self) -> Dict[str, Any]:
        s = self.get_snapshot()
        return {
            "server_time": time.time(),
            "hr": round(s.hr, 1) if s.hr is not None else None,
            "gsr": round(s.gsr, 1) if s.gsr is not None else None,
            "state": s.state,
            "rule_state": s.rule_state,
            "ml_state": s.ml_state,
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
        }

    def reset_session(self) -> None:
        with self._lock:
            self.pipeline.reset()
            self.baseline.reset()
            self.smoother.reset()
            self.fsm = StateMachine()
            self.pattern_detector = PatternDetector()
            self.alert_system = AlertSystem()
            self._prev_rule_state = None
            self._latest_hr = None
            self._latest_gsr = None
