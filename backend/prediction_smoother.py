"""
Majority vote over last N fused labels + hysteresis to reduce UI flicker.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class PredictionSmoother:
    history_size: int
    hysteresis_confirm: int

    def __post_init__(self) -> None:
        n = max(3, self.history_size)
        self._buf: Deque[str] = deque(maxlen=n)
        self._current = "CALM"
        self._pending: str | None = None
        self._pending_streak = 0

    def reset(self) -> None:
        self._buf.clear()
        self._current = "CALM"
        self._pending = None
        self._pending_streak = 0

    def push(self, label: str) -> str:
        self._buf.append(label)
        if len(self._buf) < 2:
            self._current = label
            return self._current
        counts = Counter(self._buf)
        majority = counts.most_common(1)[0][0]
        if majority == self._current:
            self._pending = None
            self._pending_streak = 0
            return self._current
        if majority != self._pending:
            self._pending = majority
            self._pending_streak = 1
        else:
            self._pending_streak += 1
        if self._pending_streak >= self.hysteresis_confirm:
            self._current = majority
            self._pending = None
            self._pending_streak = 0
        return self._current
