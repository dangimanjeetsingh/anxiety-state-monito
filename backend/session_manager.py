"""
Session lifecycle: phase state machine and session identity.

Phases: IDLE -> CALIBRATING -> MONITORING -> ENDED (see PLAN.md section 3.1).
This module holds no locks and performs no I/O; AnxietyStateService owns both.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

LOG = logging.getLogger(__name__)

PHASE_IDLE = "IDLE"
PHASE_CALIBRATING = "CALIBRATING"
PHASE_MONITORING = "MONITORING"
PHASE_ENDED = "ENDED"


def new_session_id(now: Optional[float] = None) -> str:
    """Return a filename-safe session id: YYYYmmdd-HHMMSS-xxxx."""
    ts = datetime.fromtimestamp(now if now is not None else time.time())
    return ts.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


@dataclass
class SessionState:
    id: Optional[str] = None
    label: Optional[str] = None
    phase: str = PHASE_IDLE
    started_at: Optional[float] = None          # time.time() at start
    calibrated_at: Optional[float] = None       # time.time() when baseline became ready
    ended_at: Optional[float] = None
    end_reason: Optional[str] = None
    calibration_attempts: int = 0

    @property
    def recording(self) -> bool:
        return self.phase in (PHASE_CALIBRATING, PHASE_MONITORING)

    @property
    def evaluating(self) -> bool:
        return self.phase == PHASE_MONITORING

    @property
    def active(self) -> bool:
        return self.recording

    def elapsed_s(self, now: float) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at if self.ended_at is not None else now
        return max(0.0, end - self.started_at)

    def monitored_s(self, now: float) -> float:
        """Seconds since the baseline locked (0.0 if calibration never completed)."""
        if self.calibrated_at is None:
            return 0.0
        end = self.ended_at if self.ended_at is not None else now
        return max(0.0, end - self.calibrated_at)


class SessionManager:
    """Owns the phase state machine. Caller must serialize access."""

    def __init__(self) -> None:
        self._state = SessionState()

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def phase(self) -> str:
        return self._state.phase

    def start(self, label: Optional[str], now: float) -> SessionState:
        """Begin a new session. Caller must have already reset the pipeline."""
        clean = (label or "").strip()[:64] or None
        self._state = SessionState(
            id=new_session_id(now),
            label=clean,
            phase=PHASE_CALIBRATING,
            started_at=now,
            calibration_attempts=1,
        )
        LOG.info("Session started: %s (label=%s)", self._state.id, clean)
        return self._state

    def mark_calibrated(self, now: float) -> None:
        """CALIBRATING -> MONITORING. Idempotent."""
        if self._state.phase != PHASE_CALIBRATING:
            return
        self._state.phase = PHASE_MONITORING
        self._state.calibrated_at = now
        LOG.info("Session %s: calibration complete -> MONITORING", self._state.id)

    def restart_calibration(self, now: float) -> bool:
        """Stay in CALIBRATING, same session id, attempts += 1. False if not calibrating."""
        if self._state.phase != PHASE_CALIBRATING:
            return False
        self._state.calibration_attempts += 1
        LOG.info(
            "Session %s: calibration restart (attempt %d)",
            self._state.id, self._state.calibration_attempts,
        )
        return True

    def end(self, now: float) -> Optional[SessionState]:
        """Finish the active session. Returns None if nothing was running."""
        if not self._state.active:
            return None
        self._state.end_reason = (
            "user_ended" if self._state.phase == PHASE_MONITORING else "ended_during_calibration"
        )
        self._state.ended_at = now
        self._state.phase = PHASE_ENDED
        LOG.info("Session ended: %s (%s)", self._state.id, self._state.end_reason)
        return self._state
