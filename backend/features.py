"""
Feature engineering from sliding window: stats, trends, deltas vs baseline.

Calibration phase:
  During the first N seconds (configured via BaselineConfig.calibration_seconds),
  BaselineTracker accumulates samples to compute a resting baseline.
  Until calibration is complete, compute_features() returns None so that
  no predictions are made on unreliable, transient data.

After calibration:
  The baseline is locked (computed once). An optional slow adaptive update
  can be enabled, but is OFF by default to keep the baseline stable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

from backend.pipeline import WindowPoint


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_mean(values: Sequence[float]) -> float:
    """Return the mean of *values*, or 0.0 if the sequence is empty."""
    n = len(values)
    return sum(values) / n if n > 0 else 0.0


def _safe_std(values: Sequence[float], mean: float) -> float:
    """Return population std-dev, or 0.0 if fewer than 2 samples or result is NaN."""
    n = len(values)
    if n < 2:
        return 0.0
    var = sum((x - mean) ** 2 for x in values) / n
    # Guard against floating-point rounding producing tiny negative variance
    return math.sqrt(max(var, 0.0))


def _lin_trend(values: Sequence[float]) -> float:
    """Normalized least-squares slope (slope / mean) for evenly-spaced samples. 
    Returns 0.0 on degenerate input (fewer than 2 points, zero-variance x axis, or near-zero mean)."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = _safe_mean(xs)
    mean_y = _safe_mean(values)

    # Prevent division by zero when normalizing
    if abs(mean_y) < 1e-9:
        return 0.0

    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0.0:
        return 0.0

    slope = num / den
    result = slope / mean_y

    # Guard against NaN/Inf from exotic input
    return result if math.isfinite(result) else 0.0


# ---------------------------------------------------------------------------
# FeatureVector  (unchanged public shape – do NOT alter field names/order)
# ---------------------------------------------------------------------------

@dataclass
class FeatureVector:
    mean_hr: float
    std_hr: float
    hr_trend: float
    mean_gsr: float
    std_gsr: float
    gsr_trend: float
    delta_hr: float
    delta_gsr: float
    stress_index: float
    confidence: float

    def as_list(self) -> List[float]:
        return [
            self.mean_hr,
            self.std_hr,
            self.hr_trend,
            self.mean_gsr,
            self.std_gsr,
            self.gsr_trend,
            self.delta_hr,
            self.delta_gsr,
            self.stress_index,
            self.confidence,
        ]

    @staticmethod
    def feature_names() -> List[str]:
        return [
            "mean_hr",
            "std_hr",
            "hr_trend",
            "mean_gsr",
            "std_gsr",
            "gsr_trend",
            "delta_hr",
            "delta_gsr",
            "stress_index",
            "confidence",
        ]


# ---------------------------------------------------------------------------
# BaselineTracker
# ---------------------------------------------------------------------------

class BaselineTracker:
    """Tracks resting HR/GSR baseline accumulated during a fixed calibration window.

    Calibration phase (is_calibrated == False):
        Samples are collected for *calibration_seconds*.  No predictions should
        be made during this period – the caller should check ``is_ready()``
        before calling ``compute_features()``.

    Post-calibration (is_calibrated == True):
        The baseline is locked after the window closes (computed ONCE).
        Optionally a very slow exponential moving average can update it to
        account for sensor drift, but this is **disabled by default**.

    Fallback:
        If fixed_hr / fixed_gsr are provided they are used immediately and the
        tracker is considered calibrated from the start.

    Args:
        calibration_seconds: Length of the initial resting window (seconds).
        fixed_hr:            Optional pre-set resting HR (skips dynamic calib).
        fixed_gsr:           Optional pre-set resting GSR (skips dynamic calib).
        adaptive_alpha:      EMA factor for slow drift correction after calib
                             (0.0 = fully disabled, recommended default).
    """

    def __init__(
        self,
        calibration_seconds: float,
        fixed_hr: Optional[float],
        fixed_gsr: Optional[float],
        adaptive_alpha: float = 0.0,   # disabled by default
        max_std_hr: float = 15.0,      # relaxed threshold for stability
        max_std_gsr: float = 50.0,     # relaxed threshold for stability
    ) -> None:
        self._calib_s = calibration_seconds
        self._fixed_hr = fixed_hr
        self._fixed_gsr = fixed_gsr
        self._adaptive_alpha = max(0.0, min(adaptive_alpha, 1.0))
        self._max_std_hr = max_std_hr
        self._max_std_gsr = max_std_gsr

        # Continuous drift tracking vars (> 30s)
        self._drift_hr_sign = 0
        self._drift_hr_t0: Optional[float] = None
        self._drift_gsr_sign = 0
        self._drift_gsr_t0: Optional[float] = None
        self._drift_threshold_hr = 3.0
        self._drift_threshold_gsr = 10.0

        # Accumulation buffer: stores (timestamp, hr, gsr) during calibration phase
        self._calib_buffer: List[tuple[float, float, float]] = []

        # Public baseline values
        self.baseline_hr: Optional[float] = None
        self.baseline_gsr: Optional[float] = None

        # --- Calibration state flag (requirement 1) ---
        self.is_calibrated: bool = False

        # If fixed values are provided, treat the tracker as already calibrated
        if fixed_hr is not None and fixed_gsr is not None:
            self.baseline_hr = fixed_hr
            self.baseline_gsr = fixed_gsr
            self.is_calibrated = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """Return True once the calibration phase has completed and a
        reliable baseline is available for delta computations."""
        return self.is_calibrated

    def reset(self) -> None:
        """Reset accumulation state (e.g. on sensor reconnect)."""
        self._calib_buffer.clear()
        self._drift_hr_sign = 0
        self._drift_hr_t0 = None
        self._drift_gsr_sign = 0
        self._drift_gsr_t0 = None

        if self._fixed_hr is not None and self._fixed_gsr is not None:
            # Fixed baseline: remain calibrated
            self.baseline_hr = self._fixed_hr
            self.baseline_gsr = self._fixed_gsr
            self.is_calibrated = True
        else:
            # Dynamic calibration: must re-calibrate
            self.baseline_hr = None
            self.baseline_gsr = None
            self.is_calibrated = False

    def update_with_sample(self, t: float, hr: float, gsr: float) -> None:
        """Call for each new smoothed sample.

        During calibration phase: maintains a sliding window until stability is reached.
        After calibration is locked: optionally applies slow adaptive update.
        """
        # --- Fixed baseline: nothing to do ---
        if self._fixed_hr is not None and self._fixed_gsr is not None:
            return  # already marked is_calibrated = True in __init__

        # --- Already calibrated: optional slow drift correction only ---
        if self.is_calibrated:
            self._maybe_adapt(t, hr, gsr)
            return

        # --- Calibration phase: maintain a sliding window of _calib_s length ---
        self._calib_buffer.append((t, hr, gsr))
        
        # Prune samples strictly older than _calib_s
        while self._calib_buffer and t - self._calib_buffer[0][0] > self._calib_s:
            self._calib_buffer.pop(0)

        # Check if the buffer covers at least the requested calibration time
        span = t - self._calib_buffer[0][0] if self._calib_buffer else 0.0
        
        if span >= self._calib_s * 0.95 and len(self._calib_buffer) >= 10:
            hrs = [p[1] for p in self._calib_buffer]
            gsrs = [p[2] for p in self._calib_buffer]
            mean_hr = _safe_mean(hrs)
            mean_gsr = _safe_mean(gsrs)
            std_hr = _safe_std(hrs, mean_hr)
            std_gsr = _safe_std(gsrs, mean_gsr)
            
            # If the period is stable, lock the calibration!
            # Otherwise, the buffer will continue to slide forward as new samples arrive,
            # effectively extending the calibration window until a calm period is found.
            if std_hr <= self._max_std_hr and std_gsr <= self._max_std_gsr:
                self.baseline_hr = mean_hr
                self.baseline_gsr = mean_gsr
                self.is_calibrated = True
                self._calib_buffer.clear() # Free memory

    def ensure_from_window(self, mean_hr: float, mean_gsr: float) -> None:
        """Safety fallback: if calibration produced no samples (e.g. sensor
        connected late), seed the baseline from the current window means.
        Called inside compute_features() ONLY after calibration is confirmed."""
        if self.baseline_hr is None:
            self.baseline_hr = mean_hr
        if self.baseline_gsr is None:
            self.baseline_gsr = mean_gsr

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _maybe_adapt(self, t: float, hr: float, gsr: float) -> None:
        """Slow exponential moving average update (disabled when alpha == 0).
        Only adapts if a constant directional drift persists for > 30 seconds."""
        if self._adaptive_alpha == 0.0:
            return
        
        b_hr = self.baseline_hr
        b_gsr = self.baseline_gsr
        if b_hr is None or b_gsr is None:
            return

        alpha = self._adaptive_alpha

        # HR drift
        diff_hr = hr - b_hr
        if abs(diff_hr) >= self._drift_threshold_hr:
            sign_hr = 1 if diff_hr > 0 else -1
            if sign_hr == self._drift_hr_sign:
                if self._drift_hr_t0 is not None and (t - self._drift_hr_t0) > 30.0:
                    self.baseline_hr = (1 - alpha) * b_hr + alpha * hr
            else:
                self._drift_hr_sign = sign_hr
                self._drift_hr_t0 = t
        else:
            self._drift_hr_sign = 0
            self._drift_hr_t0 = None

        # GSR drift
        diff_gsr = gsr - b_gsr
        if abs(diff_gsr) >= self._drift_threshold_gsr:
            sign_gsr = 1 if diff_gsr > 0 else -1
            if sign_gsr == self._drift_gsr_sign:
                if self._drift_gsr_t0 is not None and (t - self._drift_gsr_t0) > 30.0:
                    self.baseline_gsr = (1 - alpha) * b_gsr + alpha * gsr
            else:
                self._drift_gsr_sign = sign_gsr
                self._drift_gsr_t0 = t
        else:
            self._drift_gsr_sign = 0
            self._drift_gsr_t0 = None


# ---------------------------------------------------------------------------
# Feature Quality Scoring
# ---------------------------------------------------------------------------

def compute_feature_quality_score(
    num_raw_samples: int,
    num_valid_hrs: int,
    num_valid_gsrs: int,
    std_hr: float,
    std_gsr: float,
) -> float:
    """Computes a 0.0 to 1.0 quality score for the current feature window.
    
    Factors:
    - Volume: ratio of raw samples to expected optimal count (60).
    - Noise: ratio of valid samples surviving outlier bounds vs raw samples.
    - Variance: punishes extreme volatility usually caused by motion artifacts.
    """
    if num_raw_samples == 0:
        return 0.0
        
    # 1. Volume Score (max 1.0)
    # Assumes optimal window is ~60 samples
    volume_score = min(1.0, num_raw_samples / 60.0)
    
    # 2. Noise Score (max 1.0)
    # How much of the raw data survived outlier filtering?
    hr_ratio = num_valid_hrs / num_raw_samples
    gsr_ratio = num_valid_gsrs / num_raw_samples
    noise_score = min(hr_ratio, gsr_ratio)
    
    # 3. Variance Stability Score (max 1.0)
    # If HR std > 15.0, starts losing points. If GSR std > 60.0, starts losing points.
    hr_stab = max(0.0, 1.0 - (std_hr / 15.0))
    gsr_stab = max(0.0, 1.0 - (std_gsr / 60.0))
    variance_score = (hr_stab + gsr_stab) / 2.0
    
    # Combined weighted score: Volume (40%), Noise (40%), Variance (20%)
    final_score = (volume_score * 0.4) + (noise_score * 0.4) + (variance_score * 0.2)
    return max(0.0, min(1.0, final_score))

# ---------------------------------------------------------------------------
# compute_features
# ---------------------------------------------------------------------------

# Minimum number of samples required in the sliding window.
# Prevents noisy / near-empty windows from producing meaningless features.
_MIN_WINDOW_SAMPLES = 10


def compute_features(
    window: List[WindowPoint],
    baseline: BaselineTracker,
    now_t: float,
    *,
    stress_w_hr: float = 1.0,
    stress_w_gsr: float = 0.05,
    enable_normalization: bool = False,
) -> Optional[FeatureVector]:
    """Compute a FeatureVector for the current sliding window.

    Returns:
        FeatureVector on success.
        None if:
          • Calibration is not yet complete (prevents early predictions).
          • Window has fewer than _MIN_WINDOW_SAMPLES samples (quality gate).

    Args:
        window:        List of WindowPoint; the current data window.
        baseline:      Calibrated BaselineTracker instance.
        now_t:         Current timestamp (unused directly, kept for API compat).
        stress_w_hr:   Weight applied to delta_hr in the stress index formula.
        stress_w_gsr:  Weight applied to delta_gsr in the stress index formula.
    """

    # --- Requirement 2: Block predictions during calibration phase ---
    # Do NOT compute features until the baseline is ready.
    if not baseline.is_ready():
        return None

    # --- Requirement 5: Window quality check ---
    if len(window) < _MIN_WINDOW_SAMPLES:
        return None

    # Ensure the window covers at least 10 seconds of real time
    window_duration = window[-1].t - window[0].t
    if window_duration < 10.0:
        return None

    # --- Extract raw signal arrays safely ---
    raw_hrs = [p.hr for p in window]
    raw_gsrs = [p.gsr for p in window]

    # --- Outlier Removal ---
    # HR: Physiological clamp
    hrs = [h for h in raw_hrs if 40.0 <= h <= 180.0]

    # GSR: IQR-based filtering
    gsrs = []
    if raw_gsrs:
        sorted_gsrs = sorted(raw_gsrs)
        n = len(sorted_gsrs)
        q1 = sorted_gsrs[n // 4]
        q3 = sorted_gsrs[(n * 3) // 4]
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        gsrs = [g for g in raw_gsrs if lower_bound <= g <= upper_bound]

    # Reject the whole window if it's too noisy (>50% outliers rejected)
    min_required = len(window) / 2.0
    if len(hrs) < min_required or len(gsrs) < min_required:
        return None

    # --- Feature Normalization ---
    # Z-score normalization of the window arrays (improves certain ML models)
    if enable_normalization:
        mh = _safe_mean(hrs)
        sh = _safe_std(hrs, mh)
        hrs = [(h - mh) / sh if sh > 0 else 0.0 for h in hrs]
        
        mg = _safe_mean(gsrs)
        sg = _safe_std(gsrs, mg)
        gsrs = [(g - mg) / sg if sg > 0 else 0.0 for g in gsrs]

    # --- Basic statistics (requirement 6: NaN-safe helpers used) ---
    mean_hr = _safe_mean(hrs)
    mean_gsr = _safe_mean(gsrs)
    std_hr = _safe_std(hrs, mean_hr)
    std_gsr = _safe_std(gsrs, mean_gsr)
    hr_trend = _lin_trend(hrs)
    gsr_trend = _lin_trend(gsrs)

    # --- Baseline deltas --------------------------------------------------
    # Provides a safe fallback if the calibration phase ended with zero valid
    # samples (sensor was not ready in time).
    baseline.ensure_from_window(mean_hr, mean_gsr)

    # After ensure_from_window these are guaranteed to be non-None
    bh = baseline.baseline_hr if baseline.baseline_hr is not None else mean_hr
    bg = baseline.baseline_gsr if baseline.baseline_gsr is not None else mean_gsr

    delta_hr = mean_hr - bh
    delta_gsr = mean_gsr - bg

    # --- Requirement 4: Configurable stress index -------------------------
    # Replaces the old hard-coded: delta_hr + delta_gsr * 0.05
    # Default weights reproduce the original behaviour, but can be tuned via
    # the call-site (or eventually via config).
    stress_index = (delta_hr * stress_w_hr) + (delta_gsr * stress_w_gsr)

    # Calculate comprehensive feature quality/confidence score
    confidence = compute_feature_quality_score(
        num_raw_samples=len(window),
        num_valid_hrs=len(hrs),
        num_valid_gsrs=len(gsrs),
        std_hr=std_hr,
        std_gsr=std_gsr,
    )

    # Final NaN / Inf guard across all computed values
    def _finite(v: float, fallback: float = 0.0) -> float:
        return v if math.isfinite(v) else fallback

    return FeatureVector(
        mean_hr=_finite(mean_hr),
        std_hr=_finite(std_hr),
        hr_trend=_finite(hr_trend),
        mean_gsr=_finite(mean_gsr),
        std_gsr=_finite(std_gsr),
        gsr_trend=_finite(gsr_trend),
        delta_hr=_finite(delta_hr),
        delta_gsr=_finite(delta_gsr),
        stress_index=_finite(stress_index),
        confidence=_finite(confidence),
    )
