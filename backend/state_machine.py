"""
Finite State Machine (FSM) for anxiety state transitions.

Implements a strict automata model. Sits downstream of PredictionSmoother:

    Fusion → PredictionSmoother → StateMachine → Final State

States
------
    CALM  →  STRESS  →  ANXIETY
                ↑           ↓
              CALM      RECOVERY  →  CALM

Transitions (with required hold durations)
------------------------------------------
    CALM      → STRESS   : input == STRESS           for ≥ 3 s
    STRESS    → ANXIETY  : input == ANXIETY          for ≥ 3 s
    STRESS    → CALM     : input == CALM             for ≥ 3 s
    ANXIETY   → RECOVERY : input in {CALM, STRESS}
                           AND hr_trend < 0          for ≥ 5 s
    RECOVERY  → CALM     : input == CALM             for ≥ 5 s

Special rules
-------------
    • CALM  → ANXIETY  is blocked UNLESS stress_index > EXTREME_STRESS_INDEX
      (emergency escape hatch; still requires 3 s hold).
    • ANXIETY → CALM   is always blocked — must pass through RECOVERY.

ACTIVE state has been removed completely.
Confidence-based gating and escalation clamping have been removed in favor of strict automata holding times.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid FSM states.
VALID_STATES: frozenset[str] = frozenset({"CALM", "STRESS", "ANXIETY", "RECOVERY"})

# Minimum hold durations (seconds) for each candidate transition.
_HOLD_CALM_TO_STRESS:     float = 3.0
_HOLD_STRESS_TO_ANXIETY:  float = 3.0
_HOLD_STRESS_TO_CALM:     float = 3.0
_HOLD_ANXIETY_TO_RECOVERY: float = 5.0
_HOLD_RECOVERY_TO_CALM:   float = 5.0

# Direct CALM → ANXIETY is only allowed when the raw stress signal is extreme.
_EXTREME_STRESS_INDEX: float = 12.0
_HOLD_CALM_TO_ANXIETY_DIRECT: float = 3.0   # must hold for this long even in the emergency path


class StateMachine:
    """
    Automata-based FSM that enforces physiologically realistic state transitions.

    Candidate tracking
    ------------------
    On every call to ``update()``:
      1. Derive the *candidate* next state for the current FSM state + input.
      2. If the candidate is identical to the *previous* candidate, accumulate
         elapsed time.
      3. If the candidate differs (input changed or conditions changed), reset
         the candidate timer.
      4. When accumulated time meets or exceeds the required hold duration,
         commit the transition.

    Args:
        initial_state: Starting FSM state.  Must be one of ``VALID_STATES``.
    """

    def __init__(self, initial_state: str = "CALM") -> None:
        if initial_state not in VALID_STATES:
            raise ValueError(
                f"initial_state {initial_state!r} is not valid. "
                f"Must be one of {sorted(VALID_STATES)}."
            )
        self._state: str = initial_state

        # Candidate transition tracking
        self._candidate:       Optional[str] = None   # target state being evaluated
        self._candidate_since: float = time.time()    # when current candidate started

        LOG.debug("StateMachine initialised → %s", self._state)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Current FSM state (read-only)."""
        return self._state

    def update(
        self,
        input_state: str,
        features,       # FeatureVector — typed loosely to avoid circular import
        now_t: float,
    ) -> str:
        """
        Evaluate the automata rules and advance the FSM if a transition is due.

        Args:
            input_state: Smoothed label from ``PredictionSmoother``.
                         Unknown labels are treated as no-op.
            features:    Current ``FeatureVector``; uses ``hr_trend`` and
                         ``stress_index`` attributes.
            now_t:       ``time.time()`` value provided by the caller (avoids
                         repeated syscalls inside the lock).

        Returns:
            Current FSM state after evaluation.
        """
        # ------------------------------------------------------------------
        # Normalise input labels that the upstream pipeline may still emit.
        # ACTIVE → STRESS (nearest valid state; keeps pipeline decoupled).
        # ------------------------------------------------------------------
        effective_input = input_state
        if effective_input == "ACTIVE":
            effective_input = "STRESS"
        elif effective_input not in VALID_STATES and effective_input != "ACTIVE":
            LOG.warning(
                "StateMachine: unknown input_state %r; treating as no-op.", input_state
            )
            self._clear_candidate()
            return self._state

        hr_trend     = getattr(features, "hr_trend",     0.0)
        stress_index = getattr(features, "stress_index", 0.0)

        # ------------------------------------------------------------------
        # Derive candidate next state from current FSM state + input + features
        # ------------------------------------------------------------------
        candidate, required_hold = self._derive_candidate(
            effective_input, hr_trend, stress_index
        )

        # ------------------------------------------------------------------
        # Candidate tracking: reset timer if candidate changed
        # ------------------------------------------------------------------
        if candidate != self._candidate:
            self._candidate       = candidate
            self._candidate_since = now_t
            if candidate is not None:
                LOG.debug(
                    "FSM candidate changed: %s (from %s, input=%s)",
                    candidate, self._state, effective_input,
                )

        # ------------------------------------------------------------------
        # No actionable candidate — stay in current state
        # ------------------------------------------------------------------
        if candidate is None or required_hold is None:
            return self._state

        # ------------------------------------------------------------------
        # Check if the candidate has been held long enough
        # ------------------------------------------------------------------
        elapsed = now_t - self._candidate_since
        if elapsed >= required_hold:
            self._commit(candidate, now_t)

        return self._state

    def reset(self) -> None:
        """Reset FSM to CALM. Call this method OR re-instantiate — both are valid."""
        LOG.debug("StateMachine.reset() → CALM")
        self._state = "CALM"
        self._clear_candidate()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _derive_candidate(
        self,
        effective_input: str,
        hr_trend: float,
        stress_index: float,
    ) -> tuple[Optional[str], Optional[float]]:
        """
        Return ``(candidate_state, required_hold_seconds)`` for the current
        FSM state, or ``(None, None)`` if no valid transition exists.
        """
        s = self._state

        # ── CALM ──────────────────────────────────────────────────────────
        if s == "CALM":
            if effective_input == "STRESS":
                return "STRESS", _HOLD_CALM_TO_STRESS

            # Emergency direct path: only when physiological signal is extreme
            if (
                effective_input == "ANXIETY"
                and stress_index > _EXTREME_STRESS_INDEX
            ):
                return "ANXIETY", _HOLD_CALM_TO_ANXIETY_DIRECT

            # All other inputs from CALM → no transition
            return None, None

        # ── STRESS ────────────────────────────────────────────────────────
        if s == "STRESS":
            if effective_input == "ANXIETY":
                return "ANXIETY", _HOLD_STRESS_TO_ANXIETY
            if effective_input == "CALM":
                return "CALM", _HOLD_STRESS_TO_CALM
            # STRESS stays in STRESS
            return None, None

        # ── ANXIETY ───────────────────────────────────────────────────────
        if s == "ANXIETY":
            # ANXIETY → CALM is blocked; must pass through RECOVERY.
            # ANXIETY → RECOVERY requires input de-escalation AND falling HR.
            if effective_input in ("CALM", "STRESS") and hr_trend < 0:
                return "RECOVERY", _HOLD_ANXIETY_TO_RECOVERY
            return None, None

        # ── RECOVERY ──────────────────────────────────────────────────────
        if s == "RECOVERY":
            if effective_input == "CALM":
                return "CALM", _HOLD_RECOVERY_TO_CALM
            # If input re-escalates while in RECOVERY, go back to STRESS.
            # (ANXIETY input is unlikely after smoothing, but handle safely.)
            if effective_input in ("STRESS", "ANXIETY"):
                return "STRESS", _HOLD_CALM_TO_STRESS   # reuse 3 s hold
            return None, None

        # Unreachable guard
        return None, None

    def _commit(self, new_state: str, now_t: float) -> None:
        """Commit a pending transition and reset candidate tracking."""
        LOG.info("FSM transition: %s → %s", self._state, new_state)
        self._state           = new_state
        self._candidate       = None
        self._candidate_since = now_t

    def _clear_candidate(self) -> None:
        """Discard any pending candidate without transitioning."""
        self._candidate       = None
        self._candidate_since = time.time()