"""
Alert System module.

Triggers severity-based alerts depending on sustained anxiety states
(from the FSM) and temporal physiological patterns (from PatternDetector).
"""
from __future__ import annotations

import logging

LOG = logging.getLogger(__name__)


class AlertSystem:
    """
    Evaluates final states and patterns to trigger action-oriented alerts.
    Maintains its own duration tracking to avoid coupling with the FSM.
    """

    def __init__(self) -> None:
        self._current_state: str | None = None
        self._state_since: float = 0.0

    def update(
        self,
        state: str,
        pattern: str,
        confidence: float,
        now_t: float,
    ) -> str:
        """
        Evaluate the current pipeline outputs to determine the alert level.

        Args:
            state: The final, smoothed state from the FSM (e.g., "ANXIETY").
            pattern: The temporal pattern string from PatternDetector.
            confidence: The feature quality/confidence score (0.0 to 1.0).
            now_t: The current monotonic timestamp.

        Returns:
            A string representing the alert level ("NONE", "LOW", "MEDIUM", "HIGH").
        """
        # Duration tracking: reset timer if the FSM state changes
        if state != self._current_state:
            self._current_state = state
            self._state_since = now_t

        state_duration = now_t - self._state_since

        # 1. HIGH ALERT: True physiological anxiety sustained with high confidence
        if self._current_state == "ANXIETY" and state_duration > 10.0 and confidence > 0.6:
            return "HIGH"

        # 2. MEDIUM ALERT: Prolonged stress or a sudden spike indicating potential onset
        if (self._current_state == "STRESS" and state_duration > 20.0) or pattern == "RAPID_STRESS_SPIKE":
            return "MEDIUM"

        # 3. LOW ALERT: Early warning signs or slow returning baselines
        if pattern in ("GRADUAL_STRESS_BUILD", "SLOW_RECOVERY"):
            return "LOW"

        # 4. NONE: Nominal or insufficient evidence to alert
        return "NONE"

    def reset(self) -> None:
        """Clear internal tracking timers."""
        self._current_state = None
        self._state_since = 0.0
