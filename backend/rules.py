"""
Tier 1 rule-based anxiety / activity detection from engineered features.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.config import ThresholdConfig
from backend.features import FeatureVector


@dataclass
class RulesEngine:
    thresholds: ThresholdConfig

    def classify(self, fv: FeatureVector, previous_state: Optional[str]) -> str:
        """
        Returns one of: CALM, STRESS, ANXIETY, ACTIVE.
        Uses HR/GSR deltas, trends, and simple recovery heuristic.
        If signal confidence is low, safely downgrades the prediction.
        """
        th = self.thresholds
        prev = previous_state or "CALM"
        
        state = "CALM"

        # Strong sympathetic arousal on both channels -> anxiety unless pure motor activity
        strong_sympathetic = (
            fv.delta_hr > th.anxiety_delta_hr and fv.delta_gsr > th.anxiety_delta_gsr
        )
        # De-escalation takes priority over the raw level: the 30 s window mean
        # trails the live signal, so both deltas stay above the anxiety thresholds
        # for roughly a window after the wearer has actually started to settle.
        # Reporting ANXIETY through a clear, sustained fall kept the dashboard a
        # full minute behind the person. Falling HR from an elevated state steps
        # down one level and lets the state machine route ANXIETY -> RECOVERY.
        de_escalating = (
            prev in ("STRESS", "ANXIETY") and fv.hr_trend < th.recovery_hr_trend
        )

        if strong_sympathetic:
            # NOTE: the previous motion guard here tested `delta_gsr < activity_gsr_ceiling`
            # (25) inside a branch that already requires delta_gsr > anxiety_delta_gsr (80).
            # That is unsatisfiable, so it never ran. Motion is separated below, where the
            # GSR level genuinely is low; at full sympathetic arousal on both channels
            # there is no level-based way to tell movement from arousal.
            state = "STRESS" if de_escalating else "ANXIETY"
        elif fv.hr_trend > th.activity_hr_trend and fv.delta_gsr < th.activity_gsr_ceiling:
            # Activity without full sympathetic GSR surge
            state = "ACTIVE"
        elif de_escalating:
            # Recovery: was elevated, HR now falling
            if fv.delta_hr < th.stress_delta_hr and fv.delta_gsr < th.stress_delta_gsr:
                state = "CALM"
            else:
                state = "STRESS"
        elif fv.delta_hr > th.stress_delta_hr or fv.delta_gsr > th.stress_delta_gsr:
            # Moderate elevation
            state = "STRESS"

        # Confidence safety net: avoid false alarms from noisy data
        if fv.confidence < 0.5:
            if state == "ANXIETY":
                state = "STRESS"
            elif state == "STRESS":
                state = "CALM"

        return state
