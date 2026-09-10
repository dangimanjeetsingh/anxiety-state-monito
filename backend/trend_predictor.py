"""
Predictive Early-Warning: short-horizon linear projection of stress trends.
Extrapolates stress_index using existing hr_trend and gsr_trend to forecast
whether the user is trending toward a worse state within 15-30 seconds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.config import AppConfig
from backend.features import FeatureVector

LOG = logging.getLogger(__name__)

_STATE_SEVERITY = {
    "CALM": 0,
    "RECOVERY": 0,
    "ACTIVE": 1,
    "STRESS": 1,
    "ANXIETY": 2,
}


def _state_severity(state: str) -> int:
    return _STATE_SEVERITY.get((state or "CALM").upper(), 0)


def _more_severe(a: str, b: str) -> str:
    a_norm = (a or "CALM").upper()
    b_norm = (b or "CALM").upper()
    return a_norm if _state_severity(a_norm) >= _state_severity(b_norm) else b_norm


@dataclass
class TrendPrediction:
    active: bool
    predicted_state: Optional[str] = None
    seconds_to_transition: Optional[float] = None
    basis: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        if not self.active:
            return {"active": False}
        return {
            "active": True,
            "predicted_state": self.predicted_state,
            "seconds_to_transition": (
                round(self.seconds_to_transition, 1)
                if self.seconds_to_transition is not None
                else None
            ),
            "basis": self.basis,
        }


class TrendPredictor:
    """
    Evaluates FeatureVector and current FSM state to provide an explainable
    short-horizon linear projection (max 30s) toward elevated states.
    """

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._consecutive_falling_hr: int = 0
        self._last_prediction: TrendPrediction = TrendPrediction(active=False)

    def reset(self) -> None:
        self._consecutive_falling_hr = 0
        self._last_prediction = TrendPrediction(active=False)

    def update(
        self,
        fv: FeatureVector,
        current_state: str,
        calibrated: bool,
        *,
        input_state: Optional[str] = None,
    ) -> TrendPrediction:
        """
        Produce a trend prediction based on current features and state.

        ``current_state`` is the committed FSM output (used to know when a
        forecast has landed). ``input_state`` is the pre-FSM fused/smoothed
        label so ML overrides are reflected before hold timers expire.
        """
        # Rule: Only emit prediction when calibrated == True
        if not calibrated:
            self._consecutive_falling_hr = 0
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        min_conf = self._cfg.predict.min_confidence
        max_horizon = self._cfg.predict.max_horizon_s

        # Track consecutive falling hr_trend samples for immediate reversal clearance
        if fv.hr_trend < 0:
            self._consecutive_falling_hr += 1
        else:
            self._consecutive_falling_hr = 0

        # If the trend reverses (falling hr_trend) for 2 consecutive samples,
        # immediately clear the prediction rather than waiting for timeout.
        if self._consecutive_falling_hr >= 2:
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        # Rule: Confidence check
        if fv.confidence < min_conf:
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        # Determine target threshold based on current state.
        # Only escalate toward a worse state:
        # CALM -> target STRESS
        # STRESS / RECOVERY -> target ANXIETY
        # ANXIETY -> already at highest severity, no upward prediction
        target_state: Optional[str] = None
        target_stress_index: float = 0.0

        w_hr = self._cfg.baseline.stress_w_hr
        w_gsr = self._cfg.baseline.stress_w_gsr
        th = self._cfg.thresholds

        # Stress threshold baseline:
        # Stress rule boundary: delta_hr > stress_delta_hr (6.0) or delta_gsr > stress_delta_gsr (40.0)
        # In stress_index metric: delta_hr * w_hr + delta_gsr * w_gsr
        stress_threshold_index = (th.stress_delta_hr * w_hr) + (th.stress_delta_gsr * w_gsr)
        # Anxiety rule boundary: delta_hr > anxiety_delta_hr (12.0) and delta_gsr > anxiety_delta_gsr (80.0)
        anxiety_threshold_index = (th.anxiety_delta_hr * w_hr) + (th.anxiety_delta_gsr * w_gsr)

        fsm_state = (current_state or "CALM").upper()
        pipeline_state = _more_severe(fsm_state, input_state or fsm_state)

        # Pre-FSM pipeline may already be ANXIETY while the FSM is still holding.
        # input_state comes from fusion output (ML only when confidence gate passes
        # in fusion.py), so low-confidence ml_state alone never reaches here.
        # Clear the trend banner and let the breathing prompt handle that case.
        if _state_severity(pipeline_state) >= _state_severity("ANXIETY"):
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        # Forecast the next transition for the displayed (FSM) state.
        if fsm_state == "CALM":
            target_state = "STRESS"
            target_stress_index = stress_threshold_index
        elif fsm_state in ("STRESS", "RECOVERY", "ACTIVE"):
            target_state = "ANXIETY"
            target_stress_index = anxiety_threshold_index
        else:
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        # Keep the early warning visible until the FSM reaches the predicted
        # state. stress_index can cross the rule threshold several seconds
        # before the FSM confirms the transition (hold timers).
        if target_state == "STRESS" and fsm_state in ("STRESS", "ANXIETY"):
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction
        if target_state == "ANXIETY" and fsm_state == "ANXIETY":
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        # Compute rate of change of stress_index per second:
        # hr_trend is normalized least-squares slope (slope / mean_hr) per sample/second.
        # Absolute HR slope = hr_trend * mean_hr (bpm/sec).
        # Absolute GSR slope = gsr_trend * mean_gsr (raw units/sec).
        d_hr_dt = fv.hr_trend * fv.mean_hr
        d_gsr_dt = fv.gsr_trend * fv.mean_gsr

        # Only predict escalation on a genuinely rising trend
        if d_hr_dt <= 0 and d_gsr_dt <= 0:
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        d_stress_dt = (d_hr_dt * w_hr) + (d_gsr_dt * w_gsr)

        if d_stress_dt <= 1e-4:
            self._last_prediction = TrendPrediction(active=False)
            return self._last_prediction

        needed_delta = target_stress_index - fv.stress_index
        if needed_delta <= 0:
            # Rule thresholds are already met; the FSM may still be holding.
            sec_to_next = 1.0
            basis_str = "threshold crossed, awaiting state confirmation"
        else:
            sec_to_next = needed_delta / d_stress_dt
            basis_str = "rising stress_index trend"
            if d_hr_dt > 0 and d_gsr_dt > 0:
                basis_str = "rising HR & GSR trend"
            elif d_hr_dt > 0:
                basis_str = "rising heart rate trend"
            elif d_gsr_dt > 0:
                basis_str = "rising skin conductance trend"

        # Cap the forecast horizon at max_horizon_s (default 30s).
        # Include imminent transitions (sec_to_next near zero) — the UI
        # floors the countdown to at least 1 second.
        if sec_to_next <= max_horizon:
            self._last_prediction = TrendPrediction(
                active=True,
                predicted_state=target_state,
                seconds_to_transition=sec_to_next,
                basis=basis_str,
            )
            return self._last_prediction

        self._last_prediction = TrendPrediction(active=False)
        return self._last_prediction
