"""
Central configuration for serial I/O, thresholds, baseline, and pipeline.
Override via environment variables where noted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None or v.strip() == "":
        return default
    return int(v)


def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v is None or v.strip() == "":
        return default
    return float(v)


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class SerialConfig:
    """HC-05 / Bluetooth serial (pyserial)."""

    port: str = field(default_factory=lambda: os.environ.get("ANXIETY_COM_PORT", "COM6"))
    baudrate: int = field(default_factory=lambda: _env_int("ANXIETY_BAUD", 9600))
    timeout_s: float = field(default_factory=lambda: _env_float("ANXIETY_SERIAL_TIMEOUT", 1.0))
    reconnect_delay_s: float = field(default_factory=lambda: _env_float("ANXIETY_RECONNECT_DELAY", 2.0))
    use_mock: bool = field(default_factory=lambda: _env_bool("ANXIETY_USE_MOCK_SERIAL", False))


@dataclass
class BaselineConfig:
    """Baseline HR/GSR from initial calm period (seconds of valid samples)."""

    calibration_seconds: float = field(
        default_factory=lambda: _env_float("ANXIETY_BASELINE_CALIBRATION_S", 30.0)
    )
    # Optional fixed baseline (if both set, skips dynamic calibration)
    # Changed to None by default so it learns the wearer's actual baseline.
    fixed_hr: float | None = field(default_factory=lambda: _env_float("ANXIETY_FIXED_BASELINE_HR", None))
    fixed_gsr: float | None = field(default_factory=lambda: _env_float("ANXIETY_FIXED_BASELINE_GSR", None))

    # Stress-index weighting: stress = delta_hr * w_hr + delta_gsr * w_gsr
    # Defaults reproduce the original hard-coded formula.
    stress_w_hr: float = field(
        default_factory=lambda: _env_float("ANXIETY_STRESS_W_HR", 1.0)
    )
    stress_w_gsr: float = field(
        default_factory=lambda: _env_float("ANXIETY_STRESS_W_GSR", 0.05)
    )

    def __post_init__(self) -> None:
        # fixed_hr / fixed_gsr are already initialized by field(default_factory=...).
        # __post_init__ is only needed if env vars need to OVERRIDE the defaults.
        # Since default_factory reads the env already, nothing extra needed here.
        pass


@dataclass
class ThresholdConfig:
    """Rule-based Tier 1 thresholds (same units as smoothed HR / GSR)."""

    # High-confidence anxiety when both deltas exceed these
    anxiety_delta_hr: float = field(default_factory=lambda: _env_float("ANXIETY_THR_DELTA_HR", 12.0))
    anxiety_delta_gsr: float = field(default_factory=lambda: _env_float("ANXIETY_THR_DELTA_GSR", 80.0))
    # Stress band
    stress_delta_hr: float = field(default_factory=lambda: _env_float("ANXIETY_THR_STRESS_HR", 6.0))
    stress_delta_gsr: float = field(default_factory=lambda: _env_float("ANXIETY_THR_STRESS_GSR", 40.0))
    # Activity: strong HR rise without matching GSR rise
    activity_hr_trend: float = field(default_factory=lambda: _env_float("ANXIETY_THR_ACTIVITY_HR_TREND", 0.005))
    activity_gsr_ceiling: float = field(default_factory=lambda: _env_float("ANXIETY_THR_ACTIVITY_GSR_DELTA", 25.0))
    # Recovery: negative HR trend helps downgrade stress/anxiety
    recovery_hr_trend: float = field(default_factory=lambda: _env_float("ANXIETY_THR_RECOVERY_HR_TREND", -0.003))


@dataclass
class PipelineConfig:
    moving_average_window: int = field(default_factory=lambda: _env_int("ANXIETY_MA_WINDOW", 3))
    sliding_window_seconds: float = field(default_factory=lambda: _env_float("ANXIETY_WINDOW_S", 30.0))
    # Plausible physiological ranges after smoothing
    hr_min: float = 40.0
    hr_max: float = 210.0
    gsr_min: float = 0.0
    gsr_max: float = 1200.0


@dataclass
class MlConfig:
    confidence_fuse: float = field(default_factory=lambda: _env_float("ANXIETY_ML_CONFIDENCE", 0.75))


@dataclass
class SmoothingConfig:
    """Majority voting over last N fused labels + hysteresis."""

    history_size: int = field(default_factory=lambda: _env_int("ANXIETY_PRED_HISTORY", 7))
    hysteresis_confirm: int = field(default_factory=lambda: _env_int("ANXIETY_HYSTERESIS_CONFIRM", 2))


@dataclass
class AppConfig:
    serial: SerialConfig = field(default_factory=SerialConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    ml: MlConfig = field(default_factory=MlConfig)
    smoothing: SmoothingConfig = field(default_factory=SmoothingConfig)
    csv_log_interval_s: float = field(default_factory=lambda: _env_float("ANXIETY_CSV_LOG_INTERVAL", 1.0))


def load_config() -> AppConfig:
    return AppConfig()
