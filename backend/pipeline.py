"""
Data cleaning, moving average smoothing, and time-based sliding window buffer.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

from backend.config import PipelineConfig


@dataclass
class WindowPoint:
    t: float
    hr: float
    gsr: float


class DataPipeline:
    """
    - Rejects invalid / out-of-range readings
    - Applies moving average over last N accepted samples
    - Maintains rolling buffer of smoothed points for ~sliding_window_seconds
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._cfg = config
        self._ma_hr: Deque[float] = deque(maxlen=max(1, config.moving_average_window))
        self._ma_gsr: Deque[float] = deque(maxlen=max(1, config.moving_average_window))
        self._window: Deque[WindowPoint] = deque()

    def reset(self) -> None:
        self._ma_hr.clear()
        self._ma_gsr.clear()
        self._window.clear()

    def _in_range(self, hr: float, gsr: float) -> bool:
        return (
            self._cfg.hr_min <= hr <= self._cfg.hr_max
            and self._cfg.gsr_min <= gsr <= self._cfg.gsr_max
        )

    def push(self, hr: float, gsr: float) -> Optional[Tuple[float, float]]:
        """Return smoothed (hr, gsr) or None if rejected."""
        if not self._in_range(hr, gsr):
            return None
        self._ma_hr.append(hr)
        self._ma_gsr.append(gsr)
        if len(self._ma_hr) < self._ma_hr.maxlen:
            return None
        sm_hr = sum(self._ma_hr) / len(self._ma_hr)
        sm_gsr = sum(self._ma_gsr) / len(self._ma_gsr)
        now = time.time()
        self._window.append(WindowPoint(t=now, hr=sm_hr, gsr=sm_gsr))
        self._trim_window(now)
        return sm_hr, sm_gsr

    def _trim_window(self, now: float) -> None:
        cutoff = now - self._cfg.sliding_window_seconds
        while self._window and self._window[0].t < cutoff:
            self._window.popleft()

    def window_points(self) -> List[WindowPoint]:
        return list(self._window)

    def window_duration_s(self) -> float:
        if len(self._window) < 2:
            return 0.0
        return self._window[-1].t - self._window[0].t
