"""
Streaming aggregation of one monitoring session into the report dict (PLAN.md section 3.4).

The recorder is *fed*: AnxietyStateService calls observe() once per evaluated sample while
holding its lock. Aggregates are O(1) in memory; event lists are capped at MAX_EVENT_ITEMS.
observe() never raises — a recorder fault must never break live monitoring.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)

# --- Detection thresholds (PLAN.md section 3.6) ------------------------------
EPISODE_MIN_DURATION_S = 5.0     # a STRESS/ANXIETY FSM run shorter than this is not an episode
WARNING_GRACE_S = 10.0           # forecast confirmed if the state is reached within forecast_s + grace
RECOVERY_WINDOW_S = 60.0         # post-intervention observation window
LOW_CONFIDENCE_THRESHOLD = 0.4   # matches PatternDetector's UNSTABLE_SIGNAL gate
CHECKPOINT_INTERVAL_S = 10.0     # .partial.json write cadence
DISCONNECT_GAP_S = 3.0           # a sample gap longer than this counts as a disconnection
MAX_EVENT_ITEMS = 500            # hard cap per event list (transitions, warnings, episodes, ...)

PHASE_MONITORING = "MONITORING"
EPISODE_STATES = ("STRESS", "ANXIETY")
ALERT_LEVELS = ("LOW", "MEDIUM", "HIGH")

DISCLAIMER = (
    "Saarthi is a physiological stress and anxiety state estimation prototype for wellbeing "
    "monitoring. It is not a medical device and does not diagnose, treat, or provide clinical advice."
)


def _iso(ts: Optional[float]) -> Optional[str]:
    """Local-time ISO string for a wall-clock timestamp."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _round(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(value, digits)


def _pct(part: float, whole: float) -> Optional[float]:
    if whole <= 0:
        return None
    return round(part / whole * 100.0, 1)


def grade_reliability(*, baseline_completed: bool, monitored_duration_s: float,
                      coverage_pct: Optional[float],
                      mean_confidence: Optional[float]) -> tuple:
    """Grade a session's evidence (PLAN.md section 3.5). First matching tier wins.

    Returns (grade, reasons); every non-GOOD grade carries all of its reasons.
    """
    reasons: List[str] = []
    if not baseline_completed:
        reasons.append("baseline calibration never completed")
    if monitored_duration_s < 60.0:
        reasons.append("monitored window shorter than 60 seconds")
    if coverage_pct is not None and coverage_pct < 40.0:
        reasons.append("fewer than 40% of expected samples were usable")
    if reasons:
        return "INSUFFICIENT", reasons

    if monitored_duration_s < 180.0:
        reasons.append("monitored window shorter than 3 minutes")
    if coverage_pct is not None and coverage_pct < 70.0:
        reasons.append("under 70% sample coverage")
    if mean_confidence is not None and mean_confidence < 0.45:
        reasons.append("average signal quality was low")
    if reasons:
        return "LIMITED", reasons

    return "GOOD", []


class SessionRecorder:
    """Accumulates one session's evidence and renders it as the report dict."""

    def __init__(self, session_id: str, label: Optional[str], started_at: float,
                 target_calibration_s: float) -> None:
        self.session_id = session_id
        self.label = label
        self.started_at = started_at
        self.target_calibration_s = target_calibration_s

        # --- calibration outcome ---
        self._monitor_t0: Optional[float] = None
        self.baseline_hr: Optional[float] = None
        self.baseline_gsr: Optional[float] = None
        self.baseline_method: str = "personalized"
        self.calibration_locked_after_s: Optional[float] = None
        self.calibration_attempts: int = 1
        self.baseline_completed: bool = False

        # --- counters ---
        self.samples_evaluated = 0
        self.samples_rejected = 0
        self.conf_sum = 0.0
        self.conf_min: Optional[float] = None
        self.low_conf_samples = 0
        self.unstable_samples = 0

        # --- physiology running stats ---
        self.hr_sum = 0.0
        self.hr_min: Optional[float] = None
        self.hr_max: Optional[float] = None
        self.hr_last: Optional[float] = None
        self.hr_n = 0
        self.gsr_sum = 0.0
        self.gsr_min: Optional[float] = None
        self.gsr_max: Optional[float] = None
        self.gsr_last: Optional[float] = None
        self.gsr_n = 0
        self.peak_delta_hr: Optional[float] = None
        self.peak_delta_gsr: Optional[float] = None
        self.peak_stress_index: Optional[float] = None
        self.stress_sum = 0.0
        self.stress_n = 0
        self.peak_deviation_at_rel: Optional[float] = None

        # --- state accounting ---
        self.current_state: Optional[str] = None
        self.current_state_since: Optional[float] = None
        self.state_seconds: Dict[str, float] = {}
        self.transitions: List[Dict[str, Any]] = []

        # --- connection gaps ---
        self.disconnections: List[Dict[str, Any]] = []

        # --- alerts ---
        self.alert_counts: Dict[str, int] = {level: 0 for level in ALERT_LEVELS}
        self.peak_alert: Optional[str] = None
        self.seconds_at_high = 0.0

        # --- provenance ---
        self.fusion_source_counts: Dict[str, int] = {}
        self.ml_anxiety_adoptions = 0
        self.rule_final_agree = 0
        self.smoothing_suppressed_flips = 0
        self.ml_seen = False

        # --- patterns ---
        self.pattern_counts: Dict[str, int] = {}

        # --- raw event lists (P4 derives the analysis from these) ---
        self._warning_events: List[Dict[str, Any]] = []
        self._state_runs: List[Dict[str, Any]] = []
        self.interventions: List[Dict[str, Any]] = []

        # --- observation bookkeeping ---
        self._last_observe_t: Optional[float] = None
        self._prev_prediction_active = False
        self._prev_fused_state: Optional[str] = None
        self._prev_alert: Optional[str] = None
        self._open_run: Optional[Dict[str, Any]] = None

        # --- intervention bookkeeping ---
        self._last_obs: Dict[str, Any] = {}
        self._active_intervention: Optional[int] = None
        self._iv_hr_sum = 0.0
        self._iv_hr_n = 0
        self._recovery_index: Optional[int] = None
        self._recovery_until: Optional[float] = None
        self._recovery_start_rel: Optional[float] = None
        self._recovery_obs = 0

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def observe(self, *, now: float, phase: str, hr: Optional[float], gsr: Optional[float],
                state: Optional[str], rule_state: Optional[str], ml_state: Optional[str],
                fused_state: Optional[str], fusion_source: Optional[str],
                pattern: Optional[str], alert: Optional[str],
                features: Optional[Dict[str, float]], prediction: Optional[Dict[str, Any]],
                connection: Optional[str]) -> None:
        """Record one evaluated sample. Never raises."""
        try:
            self._observe_inner(
                now=now, phase=phase, hr=hr, gsr=gsr, state=state, rule_state=rule_state,
                ml_state=ml_state, fused_state=fused_state, fusion_source=fusion_source,
                pattern=pattern, alert=alert, features=features, prediction=prediction,
                connection=connection,
            )
        except Exception as e:  # pragma: no cover - defensive, see PLAN.md F-O
            LOG.debug("recorder observe failed: %s", e)

    def _observe_inner(self, *, now: float, phase: str, hr: Optional[float], gsr: Optional[float],
                       state: Optional[str], rule_state: Optional[str], ml_state: Optional[str],
                       fused_state: Optional[str], fusion_source: Optional[str],
                       pattern: Optional[str], alert: Optional[str],
                       features: Optional[Dict[str, float]], prediction: Optional[Dict[str, Any]],
                       connection: Optional[str]) -> None:
        dt = now - self._last_observe_t if self._last_observe_t is not None else 0.0
        self._last_observe_t = now
        rel = self.rel(now)
        prev_state = self.current_state

        # A long gap belongs to no state: record it and attribute no time.
        if dt > DISCONNECT_GAP_S:
            self._append(self.disconnections,
                         {"at_rel": _round(rel - dt), "duration_s": _round(dt)})
            dt = 0.0

        # Calibration observations feed quality only (sample counts, gaps).
        if phase != PHASE_MONITORING:
            return

        self.samples_evaluated += 1

        # --- signal quality ---
        conf = (features or {}).get("confidence")
        if conf is not None:
            self.conf_sum += conf
            self.conf_min = conf if self.conf_min is None else min(self.conf_min, conf)
            if conf < LOW_CONFIDENCE_THRESHOLD:
                self.low_conf_samples += 1
        if pattern:
            self.pattern_counts[pattern] = self.pattern_counts.get(pattern, 0) + 1
            if pattern == "UNSTABLE_SIGNAL":
                self.unstable_samples += 1

        # --- physiology ---
        if hr is not None:
            self.hr_sum += hr
            self.hr_n += 1
            self.hr_last = hr
            self.hr_min = hr if self.hr_min is None else min(self.hr_min, hr)
            self.hr_max = hr if self.hr_max is None else max(self.hr_max, hr)
        if gsr is not None:
            self.gsr_sum += gsr
            self.gsr_n += 1
            self.gsr_last = gsr
            self.gsr_min = gsr if self.gsr_min is None else min(self.gsr_min, gsr)
            self.gsr_max = gsr if self.gsr_max is None else max(self.gsr_max, gsr)

        fv = features or {}
        d_hr = fv.get("delta_hr")
        d_gsr = fv.get("delta_gsr")
        stress = fv.get("stress_index")
        if d_hr is not None and (self.peak_delta_hr is None or d_hr > self.peak_delta_hr):
            self.peak_delta_hr = d_hr
        if d_gsr is not None and (self.peak_delta_gsr is None or d_gsr > self.peak_delta_gsr):
            self.peak_delta_gsr = d_gsr
        if stress is not None:
            self.stress_sum += stress
            self.stress_n += 1
            if self.peak_stress_index is None or stress > self.peak_stress_index:
                self.peak_stress_index = stress
                self.peak_deviation_at_rel = round(rel, 1)

        # --- state accounting (by elapsed time, so gaps cannot inflate durations) ---
        if state:
            if 0.0 < dt <= DISCONNECT_GAP_S:
                self.state_seconds[state] = self.state_seconds.get(state, 0.0) + dt
            if state != self.current_state:
                if self.current_state is not None:
                    self._append(self.transitions, {
                        "at_rel": round(rel, 1), "from": self.current_state, "to": state,
                    })
                self._close_run(rel, next_state=state)
                self.current_state = state
                self.current_state_since = now
                if state in EPISODE_STATES:
                    self._open_state_run(state, rel)
            self._update_open_run(hr, d_gsr, stress, alert, pattern, rel)

        # --- alerts ---
        if alert in ALERT_LEVELS:
            if alert != self._prev_alert:
                self.alert_counts[alert] += 1
            if self.peak_alert is None or ALERT_LEVELS.index(alert) > ALERT_LEVELS.index(self.peak_alert):
                self.peak_alert = alert
            if alert == "HIGH" and 0.0 < dt <= DISCONNECT_GAP_S:
                self.seconds_at_high += dt
        self._prev_alert = alert

        # --- provenance ---
        if fusion_source:
            self.fusion_source_counts[fusion_source] = self.fusion_source_counts.get(fusion_source, 0) + 1
        if fused_state == "ANXIETY" and fusion_source in ("ml", "both"):
            self.ml_anxiety_adoptions += 1
        if rule_state and state and rule_state == state:
            self.rule_final_agree += 1
        # A fused label that changed while the smoothed FSM output held is exactly
        # what the smoother suppressed; compare against the state before this sample.
        if fused_state != self._prev_fused_state and state == prev_state \
                and self._prev_fused_state is not None:
            self.smoothing_suppressed_flips += 1
        self._prev_fused_state = fused_state
        if ml_state is not None:
            self.ml_seen = True

        # --- early-warning rising edges (P4 verifies the outcomes) ---
        active = bool(prediction and prediction.get("active"))
        if active and not self._prev_prediction_active:
            self._append(self._warning_events, {
                "at_rel": round(rel, 1), "at_abs": now,
                "predicted_state": prediction.get("predicted_state"),
                "forecast_s": prediction.get("seconds_to_transition"),
                "basis": prediction.get("basis"),
                "outcome": None, "actual_lead_time_s": None,
            })
        self._prev_prediction_active = active

        # --- interventions: the sample stream is the only durable source ---
        self._last_obs = {
            "hr": hr, "gsr": gsr, "state": state,
            "stress_index": fv.get("stress_index"), "rel": rel, "now": now,
        }
        if self._active_intervention is not None and hr is not None:
            self._iv_hr_sum += hr
            self._iv_hr_n += 1
        self._observe_recovery(now, rel, hr, state)

    def _observe_recovery(self, now: float, rel: float, hr: Optional[float],
                          state: Optional[str]) -> None:
        """Track the post-intervention observation window. Records what happened, only."""
        if self._recovery_until is None or self._recovery_index is None:
            return
        item = self._intervention(self._recovery_index)
        if item is None:
            self._clear_recovery()
            return
        self._recovery_obs += 1
        if state == "RECOVERY":
            item["entered_recovery_within_window"] = True
        if state == "CALM" and not item.get("returned_to_calm_within_window"):
            item["returned_to_calm_within_window"] = True
            start_rel = self._recovery_start_rel if self._recovery_start_rel is not None else rel
            item["time_to_calm_s"] = round(max(0.0, rel - start_rel), 1)
        if now >= self._recovery_until:
            item["hr_at_plus_60s"] = _round(hr)
            item["recovery_data"] = ("available" if self._recovery_obs >= 5 else "unavailable")
            self._clear_recovery()

    def _clear_recovery(self) -> None:
        self._recovery_until = None
        self._recovery_index = None
        self._recovery_start_rel = None
        self._recovery_obs = 0

    def _intervention(self, index: Optional[int]) -> Optional[Dict[str, Any]]:
        for item in self.interventions:
            if item.get("index") == index:
                return item
        return None

    def note_rejected_sample(self) -> None:
        """A sample arrived but produced no evaluation (out of range, or window not ready)."""
        self.samples_rejected += 1

    def note_calibrated(self, now: float, baseline_hr: Optional[float],
                        baseline_gsr: Optional[float], method: str,
                        locked_after_s: Optional[float], attempts: int) -> None:
        """The baseline locked: monitoring time starts here."""
        self._monitor_t0 = now
        self.baseline_hr = baseline_hr
        self.baseline_gsr = baseline_gsr
        self.baseline_method = method
        self.calibration_locked_after_s = locked_after_s
        self.calibration_attempts = attempts
        self.baseline_completed = True

    def note_calibration_restart(self) -> None:
        """The wearer restarted baseline measurement inside the same session."""
        self.calibration_attempts += 1

    # ------------------------------------------------------------------
    # Interventions (bodies land in P5; the surface exists from P3)
    # ------------------------------------------------------------------

    def intervention_start(self, now: float, technique: str,
                           planned_duration_s: Optional[int]) -> int:
        """Open an intervention record and return its 1-based index.

        Idempotent: a second start while one is already running returns the
        running index rather than opening an overlapping record.
        """
        if self._active_intervention is not None:
            return self._active_intervention
        # A new exercise ends the previous one's observation window early.
        self._finalize_recovery_window(truncated=True)
        obs = self._last_obs
        index = len(self.interventions) + 1
        self._append(self.interventions, {
            "index": index,
            "technique": technique,
            "started_at_rel": round(self.rel(now), 1),
            "planned_duration_s": planned_duration_s,
            "actual_duration_s": None,
            "completion": None,
            "cycles_completed": None,
            "state_at_start": obs.get("state"),
            "state_at_end": None,
            "hr_at_start": _round(obs.get("hr")),
            "hr_at_end": None,
            "hr_mean_during": None,
            "hr_at_plus_60s": None,
            "hr_change_bpm": None,
            "hr_change_pct": None,
            "gsr_at_start": _round(obs.get("gsr")),
            "gsr_at_end": None,
            "gsr_change": None,
            "stress_index_at_start": _round(obs.get("stress_index")),
            "stress_index_at_end": None,
            "entered_recovery_within_window": False,
            "returned_to_calm_within_window": False,
            "time_to_calm_s": None,
            "recovery_data": None,
        })
        if len(self.interventions) < index:      # event cap reached
            return index
        self._active_intervention = index
        self._iv_hr_sum = 0.0
        self._iv_hr_n = 0
        return index

    def intervention_stop(self, now: float, cycles_completed: Optional[int],
                          aborted: bool = False) -> None:
        """Close the active intervention and open its observation window.

        Idempotent: a stop with nothing running is a no-op, so the browser's
        duplicate stop on a natural finish cannot corrupt the record.
        """
        item = self._intervention(self._active_intervention)
        if item is None:
            return
        obs = self._last_obs
        started_rel = item.get("started_at_rel") or 0.0
        rel = self.rel(now)
        actual = round(max(0.0, rel - started_rel), 1)
        planned = item.get("planned_duration_s")

        item["actual_duration_s"] = actual
        if cycles_completed is not None:
            item["cycles_completed"] = cycles_completed
        item["state_at_end"] = obs.get("state")
        item["hr_at_end"] = _round(obs.get("hr"))
        item["gsr_at_end"] = _round(obs.get("gsr"))
        item["stress_index_at_end"] = _round(obs.get("stress_index"))
        item["hr_mean_during"] = _round(self._iv_hr_sum / self._iv_hr_n) if self._iv_hr_n else None
        if item["hr_at_start"] is not None and item["hr_at_end"] is not None:
            change = item["hr_at_end"] - item["hr_at_start"]
            item["hr_change_bpm"] = _round(change)
            if item["hr_at_start"]:
                item["hr_change_pct"] = _round(change / item["hr_at_start"] * 100.0)
        if item["gsr_at_start"] is not None and item["gsr_at_end"] is not None:
            item["gsr_change"] = _round(item["gsr_at_end"] - item["gsr_at_start"])

        if aborted:
            item["completion"] = "aborted_by_session_end"
        elif planned:
            item["completion"] = "stopped_early" if actual < planned * 0.9 else "completed"
        else:
            # NOTE(plan): completion is a claim about running the planned length.
            # With no planned duration recorded (the legacy /session/exercise alias
            # sends none) that claim cannot be made, so it stays null with an
            # `unavailable` entry rather than defaulting to "completed".
            item["completion"] = None

        self._active_intervention = None
        self._iv_hr_sum = 0.0
        self._iv_hr_n = 0
        if aborted:
            # No window to observe: the session is over.
            item["recovery_data"] = "unavailable"
            return
        self._recovery_index = item["index"]
        self._recovery_until = now + RECOVERY_WINDOW_S
        self._recovery_start_rel = rel
        self._recovery_obs = 0

    def _finalize_recovery_window(self, truncated: bool) -> None:
        """Close an observation window that never ran its full length. Never extrapolates."""
        item = self._intervention(self._recovery_index)
        if item is not None and item.get("recovery_data") is None:
            item["hr_at_plus_60s"] = None
            item["recovery_data"] = ("truncated" if (truncated and self._recovery_obs >= 5)
                                     else "unavailable")
        self._clear_recovery()

    @property
    def intervention_count(self) -> int:
        return len(self.interventions)

    @property
    def intervention_active(self) -> bool:
        return self._active_intervention is not None

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------

    def rel(self, now: float) -> float:
        """Seconds since monitoring began, or since the session started if it has not."""
        base = self._monitor_t0 if self._monitor_t0 is not None else self.started_at
        return max(0.0, now - base)

    def monitored_duration_s(self, now: float) -> float:
        if self._monitor_t0 is None:
            return 0.0
        return max(0.0, now - self._monitor_t0)

    def calibration_duration_s(self, now: float) -> float:
        if self.calibration_locked_after_s is not None:
            return self.calibration_locked_after_s
        if self._monitor_t0 is not None:
            return max(0.0, self._monitor_t0 - self.started_at)
        return max(0.0, now - self.started_at)

    def mean_confidence(self) -> Optional[float]:
        if self.samples_evaluated <= 0 or self.conf_sum <= 0:
            return None
        return round(self.conf_sum / self.samples_evaluated, 3)

    def coverage_pct(self, now: float) -> Optional[float]:
        """Evaluated samples as a share of the one-per-second samples we expected."""
        expected = self.expected_samples(now)
        if expected <= 0:
            return None
        return round(min(100.0, self.samples_evaluated / expected * 100.0), 1)

    def expected_samples(self, now: float) -> int:
        return int(round(self.monitored_duration_s(now)))

    def episodes_so_far(self, now: float) -> List[Dict[str, Any]]:
        """Qualifying STRESS/ANXIETY episodes, including one still open."""
        runs = [dict(r) for r in self._state_runs]
        if self._open_run is not None:
            live = dict(self._open_run)
            live["patterns_observed"] = list(live["patterns_observed"])
            live["duration_s"] = round(max(0.0, self.rel(now) - live["start_rel"]), 1)
            live["resolved_via"] = "open_at_session_end"
            runs.append(live)
        # A run shorter than the minimum is not an episode, so indices are assigned
        # only after the short ones are discarded.
        episodes = [r for r in runs if (r.get("duration_s") or 0.0) >= EPISODE_MIN_DURATION_S]
        for i, episode in enumerate(episodes, start=1):
            episode["index"] = i
            episode["intervention_index"] = self._overlapping_intervention(episode)
        return episodes

    def _overlapping_intervention(self, episode: Dict[str, Any]) -> Optional[int]:
        """Index of an intervention whose window overlaps this episode's window."""
        ep_start = episode["start_rel"]
        ep_end = ep_start + (episode.get("duration_s") or 0.0)
        for item in self.interventions:
            iv_start = item.get("started_at_rel")
            if iv_start is None:
                continue
            iv_end = iv_start + (item.get("actual_duration_s") or 0.0)
            if iv_start <= ep_end and ep_start <= iv_end:
                return item.get("index")
        return None

    def grade_reliability(self, now: float, status: str) -> tuple:
        """Grade this session so far. PARTIAL is forced while it is still running."""
        if status == "partial":
            return "PARTIAL", []
        return grade_reliability(
            baseline_completed=self.baseline_completed,
            monitored_duration_s=self.monitored_duration_s(now),
            coverage_pct=self.coverage_pct(now),
            mean_confidence=self.mean_confidence(),
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def live_summary(self, now: float) -> Dict[str, Any]:
        """The small `session.live` block (PLAN.md section 3.3)."""
        grade, _ = self.grade_reliability(now, status="final")
        return {
            "reliability": grade,
            "coverage_pct": self.coverage_pct(now),
            "episodes": len(self.episodes_so_far(now)),
            "warnings": len(self._warning_events),
            "interventions": len(self.interventions),
            "peak_alert": self.peak_alert,
            "intervention_active": self.intervention_active,
        }

    def build_report(self, now: float, *, status: str, end_reason: Optional[str],
                     terminal_state: Optional[str], terminal_phase: str) -> Dict[str, Any]:
        """Assemble the report dict (PLAN.md section 3.4)."""
        from backend.report_render import build_narrative   # local: avoids an import cycle
        if status != "partial":
            # An open window at session end is reported as incomplete, not guessed at.
            self._finalize_recovery_window(truncated=True)
        monitored = self.monitored_duration_s(now)
        calibration_s = self.calibration_duration_s(now)
        coverage = self.coverage_pct(now)
        mean_conf = self.mean_confidence()
        grade, reasons = self.grade_reliability(now, status)
        unavailable: Dict[str, str] = {}

        identity = {
            "id": self.session_id,
            "label": self.label,
            "started_at_iso": _iso(self.started_at),
            "ended_at_iso": _iso(now),
            "total_duration_s": _round(max(0.0, now - self.started_at)),
            "calibration_duration_s": _round(calibration_s),
            "monitored_duration_s": _round(monitored),
            "end_reason": end_reason,
            "terminal_state": terminal_state,
            "terminal_phase": terminal_phase,
        }

        quality = {
            "samples_evaluated": self.samples_evaluated,
            "samples_rejected": self.samples_rejected,
            "expected_samples": self.expected_samples(now),
            "coverage_pct": coverage,
            "mean_confidence": mean_conf,
            "min_confidence": _round(self.conf_min, 3),
            "pct_time_low_confidence": _pct(self.low_conf_samples, self.samples_evaluated),
            "unstable_signal_pct": _pct(self.unstable_samples, self.samples_evaluated),
            "disconnections": list(self.disconnections),
            "disconnect_count": len(self.disconnections),
            "total_disconnected_s": _round(sum(d["duration_s"] or 0.0 for d in self.disconnections)),
            "reliability": grade,
            "reliability_reasons": reasons,
        }

        baseline = {
            "hr": _round(self.baseline_hr),
            "gsr": _round(self.baseline_gsr),
            "method": self.baseline_method,
            "calibration_duration_s": _round(calibration_s),
            "calibration_target_s": self.target_calibration_s,
            "calibration_extended": bool(calibration_s > self.target_calibration_s * 1.05),
            "calibration_attempts": self.calibration_attempts,
            "completed": self.baseline_completed,
        }

        for item in self.interventions:
            closed = item.get("actual_duration_s") is not None
            if closed and item.get("recovery_data") in ("truncated", "unavailable") \
                    and item.get("hr_at_plus_60s") is None:
                unavailable["interventions[%d].hr_at_plus_60s" % item["index"]] = (
                    "session ended before the 60 s recovery window completed")
            if closed and item.get("completion") is None:
                unavailable["interventions[%d].completion" % item["index"]] = (
                    "no planned duration was recorded for this exercise")

        report: Dict[str, Any] = {
            "schema_version": 1,
            "status": status,
            "identity": identity,
            "quality": quality,
            "baseline": baseline,
            "interventions": list(self.interventions),
            "intervention_summary": self._intervention_summary(),
            "unavailable": unavailable,
            "disclaimer": DISCLAIMER,
        }

        if grade == "INSUFFICIENT":
            # Too little evidence to characterise the session: report the facts only.
            for section in ("physiology", "states", "early_warnings", "alerts", "provenance"):
                report[section] = None
                unavailable[section] = "; ".join(reasons) or "not enough usable data"
            report["episodes"] = []
            report["episode_count"] = 0
            report["stress_episode_count"] = 0
            report["anxiety_episode_count"] = 0
            report["narrative"] = build_narrative(report)
            return report

        report["physiology"] = self._physiology(unavailable)
        report["states"] = self._states(now)
        episodes = self.episodes_so_far(now)
        report["episodes"] = episodes
        report["episode_count"] = len(episodes)
        report["stress_episode_count"] = sum(1 for e in episodes if e["kind"] == "STRESS")
        report["anxiety_episode_count"] = sum(1 for e in episodes if e["kind"] == "ANXIETY")
        report["early_warnings"] = self._early_warnings(final=status != "partial")
        report["alerts"] = {
            "counts": dict(self.alert_counts),
            "peak_alert": self.peak_alert,
            "seconds_at_high": _round(self.seconds_at_high),
        }
        report["provenance"] = self._provenance()
        report["narrative"] = build_narrative(report)
        return report

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _intervention_summary(self) -> Dict[str, Any]:
        """Counts only. How HR moved is reported; why it moved is not claimed."""
        changes = [i["hr_change_bpm"] for i in self.interventions
                   if i.get("hr_change_bpm") is not None]
        return {
            "count": len(self.interventions),
            "n_with_hr_reduction": sum(1 for c in changes if c < 0) if changes else 0,
            "median_hr_change_bpm": _round(statistics.median(changes)) if changes else None,
        }

    def _physiology(self, unavailable: Dict[str, str]) -> Dict[str, Any]:
        if self.hr_n == 0:
            unavailable["physiology.hr"] = "no valid samples after calibration"
        if self.gsr_n == 0:
            unavailable["physiology.gsr"] = "no valid samples after calibration"
        return {
            "hr": {
                "mean": _round(self.hr_sum / self.hr_n) if self.hr_n else None,
                "min": _round(self.hr_min),
                "max": _round(self.hr_max),
                "final": _round(self.hr_last),
            },
            "gsr": {
                "mean": _round(self.gsr_sum / self.gsr_n) if self.gsr_n else None,
                "min": _round(self.gsr_min),
                "max": _round(self.gsr_max),
                "final": _round(self.gsr_last),
            },
            "peak_delta_hr": _round(self.peak_delta_hr),
            "peak_delta_gsr": _round(self.peak_delta_gsr),
            "peak_stress_index": _round(self.peak_stress_index),
            "mean_stress_index": _round(self.stress_sum / self.stress_n) if self.stress_n else None,
            "peak_deviation_at_rel": self.peak_deviation_at_rel,
        }

    def _states(self, now: float) -> Dict[str, Any]:
        seconds = {k: round(v, 1) for k, v in self.state_seconds.items()}
        total = sum(seconds.values())
        pct = {k: round(v / total * 100.0, 1) for k, v in seconds.items()} if total > 0 else {}
        return {
            "seconds": seconds,
            "pct": pct,
            "transition_count": len(self.transitions),
            "transitions": list(self.transitions),
        }

    def _early_warnings(self, final: bool) -> Dict[str, Any]:
        """Issued forecasts and how many were followed by the predicted state.

        This is a count of what happened, not an accuracy or validation figure.
        """
        items = []
        for w in self._warning_events:
            item = {k: v for k, v in w.items() if k != "at_abs"}
            if final and item.get("outcome") is None:
                item["outcome"] = "unconfirmed"
            items.append(item)
        leads = [w["actual_lead_time_s"] for w in self._warning_events
                 if w.get("actual_lead_time_s") is not None]
        return {
            "issued": len(items),
            "confirmed": sum(1 for w in items if w.get("outcome") == "confirmed"),
            "unconfirmed": sum(1 for w in items if w.get("outcome") == "unconfirmed"),
            "median_lead_time_s": _round(statistics.median(leads)) if leads else None,
            "items": items,
        }

    def _provenance(self) -> Dict[str, Any]:
        total = sum(self.fusion_source_counts.values())
        pct = ({k: round(v / total * 100.0, 1) for k, v in self.fusion_source_counts.items()}
               if total > 0 else {})
        return {
            "fusion_source_pct": pct,
            "ml_anxiety_adoptions": self.ml_anxiety_adoptions,
            "rule_final_agreement_pct": _pct(self.rule_final_agree, self.samples_evaluated),
            "smoothing_suppressed_flips": self.smoothing_suppressed_flips,
            "ml_model_available": self.ml_seen,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append(self, target: List[Any], item: Any) -> None:
        if len(target) < MAX_EVENT_ITEMS:
            target.append(item)

    def _open_state_run(self, kind: str, rel: float) -> None:
        warning = self._claim_warning(kind, rel)
        self._open_run = {
            "index": 0,   # assigned at output time, after short runs are discarded
            "kind": kind,
            "start_rel": round(rel, 1),
            "duration_s": 0.0,
            "peak_stress_index": None,
            "peak_hr": None,
            "peak_delta_gsr": None,
            "max_alert_reached": None,
            "patterns_observed": [],
            "preceded_by_early_warning": warning is not None,
            "lead_time_s": _round(rel - warning["at_rel"]) if warning else None,
            "resolved_via": None,
            "intervention_index": None,
        }

    def _claim_warning(self, kind: str, rel: float) -> Optional[Dict[str, Any]]:
        """Most recent forecast of *kind* whose window still covers this episode start.

        A forecast counts as confirmed when the state arrives within its own
        horizon plus WARNING_GRACE_S.
        """
        for warning in reversed(self._warning_events):
            if warning.get("predicted_state") != kind:
                continue
            lead = rel - (warning.get("at_rel") or 0.0)
            if lead < 0:
                continue
            horizon = warning.get("forecast_s")
            horizon = horizon if horizon is not None else 0.0
            if lead <= horizon + WARNING_GRACE_S:
                warning["outcome"] = "confirmed"
                warning["actual_lead_time_s"] = round(lead, 1)
                return warning
            break   # older warnings are further away still
        return None

    def _update_open_run(self, hr: Optional[float], delta_gsr: Optional[float],
                         stress: Optional[float], alert: Optional[str],
                         pattern: Optional[str], rel: float) -> None:
        run = self._open_run
        if run is None:
            return
        run["duration_s"] = round(max(0.0, rel - run["start_rel"]), 1)
        if hr is not None and (run["peak_hr"] is None or hr > run["peak_hr"]):
            run["peak_hr"] = round(hr, 1)
        if delta_gsr is not None and (run["peak_delta_gsr"] is None or delta_gsr > run["peak_delta_gsr"]):
            run["peak_delta_gsr"] = round(delta_gsr, 1)
        if stress is not None and (run["peak_stress_index"] is None or stress > run["peak_stress_index"]):
            run["peak_stress_index"] = round(stress, 1)
        if alert in ALERT_LEVELS:
            current = run["max_alert_reached"]
            if current is None or ALERT_LEVELS.index(alert) > ALERT_LEVELS.index(current):
                run["max_alert_reached"] = alert
        if pattern and pattern != "NORMAL" and pattern not in run["patterns_observed"]:
            run["patterns_observed"].append(pattern)

    def _close_run(self, rel: float, next_state: Optional[str]) -> None:
        """Close the open episode. Never synthesizes a resolution."""
        run = self._open_run
        if run is None:
            return
        run["duration_s"] = round(max(0.0, rel - run["start_rel"]), 1)
        if next_state == "RECOVERY":
            run["resolved_via"] = "RECOVERY"
        elif next_state == "CALM":
            run["resolved_via"] = "direct_calm"
        else:
            # NOTE(plan): STRESS -> ANXIETY is an escalation, not a resolution, so
            # resolved_via stays null and the run is tagged instead.
            run["resolved_via"] = None
            if "escalated" not in run["patterns_observed"]:
                run["patterns_observed"].append("escalated")
        self._append(self._state_runs, run)
        self._open_run = None


def _human_duration(seconds: float) -> str:
    """'6 min 14 s' / '42 s' — used by the narrative."""
    total = int(round(max(0.0, seconds)))
    if total < 60:
        return "%d s" % total
    return "%d min %02d s" % (total // 60, total % 60)
