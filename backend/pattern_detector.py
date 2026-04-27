"""
Pattern Detector module.

Detects temporal physiological patterns from recent feature history over the last ~60 seconds.
Operates on FeatureVectors incrementally without mutating them.
"""
from __future__ import annotations

import collections
from typing import Deque, Tuple

# We type hint loosely here to avoid strict circular dependency if not needed,
# or we can assume it follows the shape of backend.features.FeatureVector


class PatternDetector:
    """
    Analyzes sequences of FeatureVectors over a rolling window to detect
    higher-level physiological patterns.
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        # Buffer stores tuples of (timestamp, FeatureVector)
        self.buffer: Deque[Tuple[float, any]] = collections.deque()

    def update(self, fv, now_t: float) -> str:
        """
        Ingest a new FeatureVector, update the temporal window, and
        evaluate the current physiological pattern.

        Args:
            fv: Current FeatureVector.
            now_t: Current monotonic timestamp.

        Returns:
            A string representing the detected pattern.
        """
        # 1. Update internal buffer and evict old entries
        self.buffer.append((now_t, fv))
        while self.buffer and now_t - self.buffer[0][0] > self.window_seconds:
            self.buffer.popleft()

        # 2. Evaluate Unstable Signal first (data quality gate)
        # Using typical variance bounds (e.g., hr > 15, gsr > 50) or low confidence.
        if getattr(fv, "confidence", 1.0) < 0.4:
            return "UNSTABLE_SIGNAL"
        
        std_hr = getattr(fv, "std_hr", 0.0)
        std_gsr = getattr(fv, "std_gsr", 0.0)
        if std_hr > 15.0 or std_gsr > 50.0:
            return "UNSTABLE_SIGNAL"

        # 3. RAPID_STRESS_SPIKE
        # Look for a sharp delta_hr increase (> +8) and delta_gsr increase
        # within the last 5-10 seconds.
        past_5_10 = [
            item for item in self.buffer 
            if (now_t - 10.0) <= item[0] <= (now_t - 5.0)
        ]
        if past_5_10:
            # Compare current against the oldest point in that 5-10s window
            past_fv = past_5_10[0][1]
            delta_hr_diff = getattr(fv, "delta_hr", 0.0) - getattr(past_fv, "delta_hr", 0.0)
            delta_gsr_diff = getattr(fv, "delta_gsr", 0.0) - getattr(past_fv, "delta_gsr", 0.0)

            if delta_hr_diff > 8.0 and delta_gsr_diff > 0.5:
                return "RAPID_STRESS_SPIKE"

        # 4. GRADUAL_STRESS_BUILD
        # Steady increase in stress_index over 20-40 seconds.
        past_20_40 = [
            item for item in self.buffer 
            if (now_t - 40.0) <= item[0] <= (now_t - 20.0)
        ]
        if past_20_40:
            past_fv = past_20_40[0][1]
            stress_diff = getattr(fv, "stress_index", 0.0) - getattr(past_fv, "stress_index", 0.0)
            
            # If stress index has drifted upwards decently over the longer window
            if stress_diff > 1.5:
                return "GRADUAL_STRESS_BUILD"

        # 5. SLOW_RECOVERY
        # State moving toward calm (falling HR), but very slowly
        hr_trend = getattr(fv, "hr_trend", 0.0)
        if -0.5 < hr_trend < -0.01:
            return "SLOW_RECOVERY"

        # 6. NORMAL (Fallback)
        return "NORMAL"

    def reset(self) -> None:
        """Clear the historical buffer."""
        self.buffer.clear()
