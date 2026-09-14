# SAARTHI — Implementation Plan: Session Lifecycle & Session Intelligence

**Status:** APPROVED FOR IMPLEMENTATION — not yet started
**Design:** Opus planning pass. **Execution target:** smaller models (Sonnet-class).
**Scope:** Two features — (F1) Session Lifecycle & Personalized Calibration, (F2) Session Intelligence / Session Report.

---

## 0. HOW TO USE THIS PLAN (read this first, every time)

This plan was written against a **verified reading of the existing codebase**. The facts in Section 1 were
checked against the real files. Trust them, but re-read the specific file before you edit it.

### Rules for the executing model

1. **Work one PHASE at a time.** Phases are in Section 4, numbered P1..P7. Each phase is independently
   shippable: after finishing a phase the app must still run and the live dashboard must still work.
   Never start P(n+1) before P(n) passes its own acceptance checks.
2. **Do not refactor anything this plan does not name.** No renaming, no reformatting, no "while I am
   here" cleanups, no type-annotation sweeps, no dependency additions.
3. **Read the whole target file before your first edit to it.** Match existing style: the codebase uses
   `from __future__ import annotations`, dataclasses, module-level `LOG = logging.getLogger(__name__)`,
   double-quoted strings, and docstrings on public methods.
4. **Additive-first.** Every API/JSON change here is additive. If you find yourself deleting or renaming an
   existing snapshot field, route, or CSV column, you have misread the plan — stop.
5. **No new Python dependencies.** `requirements.txt` must not change. Standard library only for new code
   (`json`, `csv`, `uuid`, `datetime`, `statistics`, `pathlib`, `threading`, `re`).
6. **No new frontend dependencies.** Chart.js and chartjs-plugin-annotation are already loaded via CDN in
   `frontend/index.html`. Do not add more `<script src>` tags.
7. **Exact names matter.** Field names, phase strings, route paths, and enum values in this plan are the
   contract between backend and frontend. Use them verbatim, including capitalization.
8. **When this plan is ambiguous, pick the simpler option and add a `# NOTE(plan):` comment** saying what
   you chose. Do not invent new features, endpoints, or UI surfaces.
9. **Never make medical claims** in code comments, UI copy, or generated report text. Language rules are in
   Section 6.
10. **Run acceptance checks in mock mode** (`ANXIETY_USE_MOCK_SERIAL=1`). No hardware required.

### Commands

Install once:

```bash
python -m pip install -r requirements.txt
```

Run in mock mode (PowerShell):

```bash
$env:ANXIETY_USE_MOCK_SERIAL=1; python app.py
```

Run in mock mode with fast calibration (use this while developing — saves 20 s per restart):

```bash
$env:ANXIETY_USE_MOCK_SERIAL=1; $env:ANXIETY_BASELINE_CALIBRATION_S=10; python app.py
```

Dashboard: `http://127.0.0.1:5000/` — raw snapshot: `http://127.0.0.1:5000/data`

---

## 1. VERIFIED FACTS ABOUT THE EXISTING SYSTEM

### 1.1 Runtime shape

```
app.py
  load_config()                      -> backend/config.py
  AnxietyStateService(cfg)           -> backend/state_service.py
  service.start_reader()             -> opens CSV, starts BluetoothReader thread
  create_app(service)                -> backend/flask_app.py (threaded=True, use_reloader=False)
```

Per-sample pipeline, all inside `AnxietyStateService._on_sample()` under `self._lock`:

```
Sample(gsr, hr, raw_line)
  -> snapshot.hr/gsr updated immediately (raw, pre-smoothing)
  -> DataPipeline.push()          -> None if out of range OR moving-average buffer not full (N=3)
  -> BaselineTracker.update_with_sample()
  -> DataPipeline.window_points() -> 30 s sliding window
  -> compute_features()           -> None if (a) baseline not ready, (b) <10 samples,
                                             (c) window span <10 s, (d) >50% outliers
  -> RulesEngine.classify()
  -> MlPredictor.predict()
  -> FusionEngine.fuse()
  -> PredictionSmoother.push()    -> majority vote (7) + hysteresis (2)
  -> StateMachine.update()        -> CALM/STRESS/ANXIETY/RECOVERY with hold timers
  -> PatternDetector.update()
  -> AlertSystem.update()
  -> TrendPredictor.update()
  -> rebuild DashboardSnapshot
  -> _maybe_log_csv()             -> throttled by cfg.csv_log_interval_s (1.0 s)
```

### 1.2 Facts that directly shape this plan

- **F-A: `reset_session()` already exists** in `backend/state_service.py` and correctly resets `pipeline`,
  `baseline`, `smoother`, `fsm` (re-instantiated), `pattern_detector`, `alert_system`, `trend_predictor`,
  `_prev_rule_state`, `_latest_hr`, `_latest_gsr`. **It has no HTTP route.** It is the session-boundary
  primitive. Reuse it; do not rewrite it.
- **F-B: The frontend is a pure function of the snapshot.** `render(d)` in `frontend/js/app.js` derives all
  DOM state from the one JSON object delivered by `/stream`. **Consequence: if session phase lives in the
  snapshot, browser refresh works with no extra effort.** Preserve this — do not introduce long-lived
  client-side session state.
- **F-C: Calibration gating already works.** `compute_features()` returns `None` while
  `baseline.is_ready()` is False, so no predictions happen during calibration. The
  CALIBRATING -> MONITORING trigger is simply `baseline.is_ready()` flipping to True.
- **F-D: `BaselineTracker` slides its buffer until it finds a stable window.** In `backend/features.py`,
  `update_with_sample()` prunes samples older than `calibration_seconds` and only locks the baseline when
  `span >= calib_s * 0.95 AND len >= 10 AND std_hr <= 15 AND std_gsr <= 50`. If the wearer fidgets,
  calibration takes **indefinitely long with no user-visible explanation**. This is the system's worst
  live-demo failure mode. P2 fixes it.
- **F-E: The frontend calibration progress ring is wrong.** `app.js` computes progress as
  `d.window_samples / CALIBRATION_TARGET_SAMPLES` (30). But `window_samples` is the **30-second sliding
  window** length, which saturates at ~30 and then sits there forever while the baseline buffer keeps
  sliding. The ring reaches 100% and hangs. P2 replaces the data source for this ring.
- **F-F: Everything a report needs is already computed every second and then discarded** — `state`,
  `rule_state`, `ml_state`, `fusion_source`, `pattern`, `alert`, `prediction{}`, all 10 features,
  `baseline_hr/gsr`, `calibrated`. F2 is an accumulation problem, not a computation problem.
- **F-G: The breathing intervention is browser-only and non-durable.** `exerciseBuffer`, `exerciseStartHr`,
  `exerciseStartState`, `showRecoverySummary()` all live in `app.js`. Only the strings `"start"` / `"stop"`
  reach the backend via `POST /session/exercise` -> `log_exercise_event()`, which writes one CSV row with
  `raw_line = "EXERCISE_START"` and `exercise_event = "start"`. A page refresh mid-exercise destroys the
  record. P5 fixes this.
- **F-H: There is a latent CSV header bug.** `_open_csv()` writes a header **only when the file does not
  exist**. `fieldnames` now includes `exercise_event` (10 columns), but the live `data/logs/physio_log.csv`
  has a 9-column header written before that field was added, so rows appended since then have an extra
  unlabeled column. **Any CSV schema change must rotate the file, not just add a column.** P3 handles this.
- **F-I: `AnxietyStateService` uses a single `threading.Lock`** (`self._lock`). The reader thread calls
  `_on_sample` / `_on_status`; Flask request threads call `get_snapshot` / `to_json_dict` /
  `log_exercise_event`. All new mutating methods must take the same lock. **Do not do slow file I/O while
  holding the lock** beyond what the existing CSV `flush()` already does.
- **F-J: `PatternDetector.update()` returns exactly one of** `UNSTABLE_SIGNAL`, `RAPID_STRESS_SPIKE`,
  `GRADUAL_STRESS_BUILD`, `SLOW_RECOVERY`, `NORMAL`.
- **F-K: `AlertSystem.update()` returns exactly one of** `NONE`, `LOW`, `MEDIUM`, `HIGH`.
- **F-L: `StateMachine` states are exactly** `CALM`, `STRESS`, `ANXIETY`, `RECOVERY` (`VALID_STATES`).
  `ACTIVE` is normalized to `STRESS` at FSM entry. `ANXIETY -> CALM` is blocked; it must pass through
  `RECOVERY`.
- **F-M: `TrendPrediction.to_dict()`** returns `{"active": false}` or
  `{"active": true, "predicted_state", "seconds_to_transition", "basis"}`.
- **F-N: `FusionEngine`** sets `source` to `"rules"`, `"ml"`, or `"both"`. ML only overrides rules for
  `ANXIETY` when `ml_confidence * feature_confidence >= cfg.ml.confidence_fuse` (0.75).
- **F-O: `_on_sample` already has a broad `try/except`** around the evaluation block that falls back to
  pure rules. New recorder calls must be **outside** that try block and individually guarded, so a recorder
  bug can never break live monitoring.

### 1.3 Existing snapshot fields — DO NOT CHANGE ANY OF THESE

`server_time`, `hr`, `gsr`, `state`, `rule_state`, `ml_state`, `fused_state`, `fusion_source`,
`connection`, `connection_detail`, `sensor_warning`, `baseline_hr`, `baseline_gsr`, `features`,
`window_samples`, `calibrated`, `pattern`, `alert`, `prediction`.

### 1.4 Existing routes — DO NOT CHANGE ANY OF THESE

`GET /`, `GET /data`, `GET /stream`, `POST /session/exercise`.

---

## 2. INVARIANTS AND DO-NOT-TOUCH LIST

### 2.1 Hard invariants — violating any of these means the phase failed

1. `ANXIETY_USE_MOCK_SERIAL=1 python app.py` starts with no traceback.
2. `GET /data` returns valid JSON containing **every** field in Section 1.3, with unchanged types.
3. `GET /stream` still emits one JSON payload per second.
4. The live dashboard still renders HR, GSR, the state card, the connection pill, the 60-point chart, the
   state transition markers, the calibration banner, the prediction strip, and the breathing modal.
5. Real-time prediction output is **unchanged** for the same input: rules, ML, fusion, smoothing, FSM,
   patterns, alerts, and trend forecast logic are untouched.
6. CSV logging never stops. Raw rows are written even when no session is running.
7. `requirements.txt` unchanged.
8. A recorder or report exception can never break live monitoring (see F-O).

### 2.2 Files that MUST NOT be modified

```
backend/bt_reader.py
backend/pipeline.py
backend/rules.py
backend/ml_predictor.py
backend/fusion.py
backend/prediction_smoother.py
backend/state_machine.py
backend/pattern_detector.py
backend/alert_system.py
backend/trend_predictor.py
ml/train.py
ml/model.pkl
ml/scaler.pkl
ml/data/training_data.csv
requirements.txt
```

### 2.3 Files that WILL be modified

| File | Change | Risk |
|---|---|---|
| `backend/paths.py` | ADD `sessions_dir()` only. Nothing else. | Low |
| `backend/config.py` | ADD `SessionConfig` dataclass + one field on `AppConfig`. | Low |
| `backend/features.py` | ADD calibration-telemetry to `BaselineTracker`. `compute_features()` **unchanged**. | Low |
| `backend/state_service.py` | Own session manager + recorder; gate evaluation; add `session` to snapshot; CSV v2. | **Medium — the only delicate file** |
| `backend/flask_app.py` | New routes, additive only. | Low |
| `frontend/index.html` | ADD session controls, start dialog, report panel, sessions list. | Low |
| `frontend/js/app.js` | Phase gating inside `render()`; report rendering; richer intervention payload. | Medium |
| `frontend/css/style.css` | ADD new rules **at the end of the file**. Do not edit existing rules. | Low |
| `README.md` | Document new routes/fields (P7). | Low |

### 2.4 New files

```
backend/session_manager.py    phase state machine + session identity
backend/session_recorder.py   streaming aggregation -> report dict
backend/report_render.py      report dict -> narrative text + standalone HTML (stdlib only)
```

---

## 3. DATA CONTRACTS

Implement these exactly. They are the interface between phases and between backend and frontend.

### 3.1 Session phases

Exactly four strings. No others.

```
"IDLE"          no session; reader running; raw HR/GSR shown; no evaluation; no recording
"CALIBRATING"   session active; recording; baseline being measured; compute_features() returns None
"MONITORING"    session active; recording; full evaluation and prediction
"ENDED"         session finished; report available; no evaluation; no recording
```

Legal transitions only:

```
IDLE        -> CALIBRATING     POST /session/start
CALIBRATING -> MONITORING      automatic, when baseline.is_ready() becomes True
CALIBRATING -> ENDED           POST /session/end   (end_reason "ended_during_calibration")
CALIBRATING -> CALIBRATING     POST /session/calibration/restart  (same session id, attempts += 1)
MONITORING  -> ENDED           POST /session/end   (end_reason "user_ended")
ENDED       -> CALIBRATING     POST /session/start (new session id)
IDLE        -> IDLE            POST /session/end   -> 409 no_active_session
```

`recording` is True in `CALIBRATING` and `MONITORING` only.
`evaluating` is True in `MONITORING` only.

### 3.2 Session id format

`YYYYmmdd-HHMMSS-xxxx`, where `xxxx` is the first 4 hex chars of `uuid.uuid4().hex`. Local time.
Example: `20260912-193004-a1b2`. Safe as a Windows filename.

### 3.3 Snapshot addition — ONE new top-level key: `session`

Added in `to_json_dict()`. All Section 1.3 fields keep their names, types, and meanings.

```json
"session": {
  "phase": "MONITORING",
  "id": "20260912-193004-a1b2",
  "label": "Visitor 12",
  "started_at": 1789000000.0,
  "elapsed_s": 214.0,
  "monitored_s": 181.0,
  "recording": true,
  "evaluating": true,
  "calibration": {
    "method": "personalized",
    "progress": 1.0,
    "elapsed_s": 33.0,
    "target_s": 30.0,
    "stable": true,
    "stalled": false,
    "paused": false,
    "attempts": 1
  },
  "live": {
    "reliability": "GOOD",
    "coverage_pct": 97.2,
    "episodes": 1,
    "warnings": 2,
    "interventions": 1,
    "peak_alert": "MEDIUM",
    "intervention_active": false
  }
}
```

When `phase == "IDLE"`, emit exactly:

```json
"session": {
  "phase": "IDLE", "id": null, "label": null, "started_at": null,
  "elapsed_s": 0.0, "monitored_s": 0.0, "recording": false, "evaluating": false,
  "calibration": null, "live": null
}
```

When `phase == "ENDED"`, `id` / `label` / `started_at` describe the **just-ended** session, `recording` and
`evaluating` are False, and `live` carries the final summary numbers so the UI can show them immediately.

### 3.4 Report JSON schema (`data/sessions/<id>.json`)

Single source of truth. The in-app view, the HTML download, and the narrative are all projections of it.
Any value that cannot be computed is `null` **and** gets an entry in `unavailable` explaining why.
**Never substitute 0 for unknown.**

```json
{
  "schema_version": 1,
  "status": "final",

  "identity": {
    "id": "20260912-193004-a1b2",
    "label": "Visitor 12",
    "started_at_iso": "2026-09-12T19:30:04",
    "ended_at_iso": "2026-09-12T19:36:18",
    "total_duration_s": 374.0,
    "calibration_duration_s": 33.0,
    "monitored_duration_s": 341.0,
    "end_reason": "user_ended",
    "terminal_state": "CALM",
    "terminal_phase": "ENDED"
  },

  "quality": {
    "samples_evaluated": 331,
    "samples_rejected": 12,
    "expected_samples": 341,
    "coverage_pct": 97.1,
    "mean_confidence": 0.78,
    "min_confidence": 0.31,
    "pct_time_low_confidence": 4.2,
    "unstable_signal_pct": 3.6,
    "disconnections": [{ "at_rel": 120.0, "duration_s": 6.0 }],
    "disconnect_count": 1,
    "total_disconnected_s": 6.0,
    "reliability": "GOOD",
    "reliability_reasons": []
  },

  "baseline": {
    "hr": 69.8,
    "gsr": 488.2,
    "method": "personalized",
    "calibration_duration_s": 33.0,
    "calibration_target_s": 30.0,
    "calibration_extended": true,
    "calibration_attempts": 1,
    "completed": true
  },

  "physiology": {
    "hr":  { "mean": 74.1, "min": 66.0, "max": 103.0, "final": 71.0 },
    "gsr": { "mean": 521.4, "min": 470.0, "max": 690.0, "final": 495.0 },
    "peak_delta_hr": 33.2,
    "peak_delta_gsr": 201.8,
    "peak_stress_index": 43.3,
    "mean_stress_index": 6.1,
    "peak_deviation_at_rel": 188.0
  },

  "states": {
    "seconds": { "CALM": 240.0, "STRESS": 61.0, "ANXIETY": 22.0, "RECOVERY": 18.0 },
    "pct":     { "CALM": 70.4,  "STRESS": 17.9, "ANXIETY": 6.5,  "RECOVERY": 5.3 },
    "transition_count": 6,
    "transitions": [{ "at_rel": 96.0, "from": "CALM", "to": "STRESS" }]
  },

  "episodes": [
    {
      "index": 1,
      "kind": "ANXIETY",
      "start_rel": 96.0,
      "duration_s": 83.0,
      "peak_stress_index": 43.3,
      "peak_hr": 103.0,
      "peak_delta_gsr": 201.8,
      "max_alert_reached": "HIGH",
      "patterns_observed": ["RAPID_STRESS_SPIKE", "GRADUAL_STRESS_BUILD"],
      "preceded_by_early_warning": true,
      "lead_time_s": 11.0,
      "resolved_via": "RECOVERY",
      "intervention_index": 1
    }
  ],
  "episode_count": 1,
  "stress_episode_count": 0,
  "anxiety_episode_count": 1,

  "early_warnings": {
    "issued": 2,
    "confirmed": 1,
    "unconfirmed": 1,
    "median_lead_time_s": 11.0,
    "items": [
      {
        "at_rel": 85.0, "predicted_state": "STRESS", "forecast_s": 14.0,
        "basis": "rising HR & GSR trend", "outcome": "confirmed", "actual_lead_time_s": 11.0
      }
    ]
  },

  "alerts": {
    "counts": { "LOW": 3, "MEDIUM": 2, "HIGH": 1 },
    "peak_alert": "HIGH",
    "seconds_at_high": 14.0
  },

  "interventions": [
    {
      "index": 1,
      "technique": "box_4_4_4_4",
      "started_at_rel": 150.0,
      "planned_duration_s": 60,
      "actual_duration_s": 60.0,
      "completion": "completed",
      "cycles_completed": 3,
      "state_at_start": "ANXIETY",
      "state_at_end": "RECOVERY",
      "hr_at_start": 98.0, "hr_at_end": 87.0, "hr_mean_during": 92.4, "hr_at_plus_60s": 78.0,
      "hr_change_bpm": -11.0, "hr_change_pct": -11.2,
      "gsr_at_start": 660.0, "gsr_at_end": 590.0, "gsr_change": -70.0,
      "stress_index_at_start": 38.1, "stress_index_at_end": 21.4,
      "entered_recovery_within_window": true,
      "returned_to_calm_within_window": false,
      "time_to_calm_s": null,
      "recovery_data": "available"
    }
  ],
  "intervention_summary": { "count": 1, "n_with_hr_reduction": 1, "median_hr_change_bpm": -11.0 },

  "provenance": {
    "fusion_source_pct": { "rules": 88.2, "ml": 7.6, "both": 4.2 },
    "ml_anxiety_adoptions": 12,
    "rule_final_agreement_pct": 81.3,
    "smoothing_suppressed_flips": 27,
    "ml_model_available": true
  },

  "narrative": ["Session 'Visitor 12' ran for 6 min 14 s, of which 5 min 41 s was monitored after calibration.", "..."],

  "unavailable": { "physiology.hr.final": "no valid samples after calibration" },

  "disclaimer": "Saarthi is a physiological stress and anxiety state estimation prototype for wellbeing monitoring. It is not a medical device and does not diagnose, treat, or provide clinical advice."
}
```

Enum values:

- `status`: `"final"` | `"partial"` | `"interrupted"`
- `end_reason`: `"user_ended"` | `"ended_during_calibration"` | `"interrupted"`
- `baseline.method`: `"personalized"` | `"fixed"`
- `episodes[].kind`: `"STRESS"` | `"ANXIETY"`
- `episodes[].resolved_via`: `"RECOVERY"` | `"direct_calm"` | `"open_at_session_end"`
- `early_warnings.items[].outcome`: `"confirmed"` | `"unconfirmed"`
- `interventions[].completion`: `"completed"` | `"stopped_early"` | `"aborted_by_session_end"`
- `interventions[].recovery_data`: `"available"` | `"truncated"` | `"unavailable"`
- `quality.reliability`: `"GOOD"` | `"LIMITED"` | `"INSUFFICIENT"` | `"PARTIAL"`

### 3.5 Reliability grading — implement exactly

Evaluate in this order; first match wins. Every non-GOOD grade appends human-readable strings to
`reliability_reasons` (append **all** matching reasons, not just the first).

```
INSUFFICIENT if any of:
    baseline.completed is False    -> "baseline calibration never completed"
    monitored_duration_s < 60      -> "monitored window shorter than 60 seconds"
    coverage_pct < 40              -> "fewer than 40% of expected samples were usable"

LIMITED if any of:
    monitored_duration_s < 180     -> "monitored window shorter than 3 minutes"
    coverage_pct < 70              -> "under 70% sample coverage"
    mean_confidence < 0.45         -> "average signal quality was low"

GOOD otherwise.

PARTIAL is not graded — it is forced whenever status == "partial" (session still running).
```

Rendering consequences:

- `INSUFFICIENT` -> populate `identity`, `quality`, `baseline` only. Set `physiology`, `states`,
  `episodes` (to `[]`), `early_warnings`, `alerts`, `provenance` to `null`, and add `unavailable` entries
  keyed by section name with the reason. Interventions are still listed if any occurred (they are factual
  events), with recovery metrics following the §3.4 rules.
- `LIMITED` -> populate everything; the UI stamps each section "provisional".
- `GOOD` -> populate everything.

### 3.6 Detection thresholds — define once, at the top of `session_recorder.py`

```python
EPISODE_MIN_DURATION_S   = 5.0    # a STRESS/ANXIETY FSM run shorter than this is not an episode
WARNING_GRACE_S          = 10.0   # forecast confirmed if the state is reached within forecast_s + grace
RECOVERY_WINDOW_S        = 60.0   # post-intervention observation window
LOW_CONFIDENCE_THRESHOLD = 0.4    # matches PatternDetector's UNSTABLE_SIGNAL gate
CHECKPOINT_INTERVAL_S    = 10.0   # .partial.json write cadence
DISCONNECT_GAP_S         = 3.0    # a sample gap longer than this counts as a disconnection
MAX_EVENT_ITEMS          = 500    # hard cap per event list (transitions, warnings, episodes, ...)
```

### 3.7 CSV schema v2

New `fieldnames`, in this exact order:

```python
[
    "timestamp_iso", "session_id", "session_phase",
    "hr", "gsr", "raw_line",
    "rule_state", "ml_state", "fused_state", "final_state",
    "connection", "exercise_event",
]
```

Rotation rule (fixes F-H). In `_open_csv()`, **before** opening for append:

1. If `physio_log.csv` exists, read its first line.
2. If that line (stripped) != the v2 header joined by commas, rename the file to
   `physio_log.pre_sessions.csv`. If that name is taken, append `-1`, `-2`, ... until free.
3. Open `physio_log.csv` fresh and write the v2 header.

Rows written while `phase` is `IDLE` or `ENDED` carry `session_id = ""` and the current phase string. The
raw trace is never lost.

### 3.8 Files on disk

```
data/sessions/<id>.json                 immutable final report (written on end_session)
data/sessions/<id>.partial.json         checkpoint every 10 s (deleted on clean end)
data/logs/physio_log.csv                v2 header
data/logs/physio_log.pre_sessions.csv   one-time rotation of the old log
```

No database. No new dependencies.

### 3.9 HTTP API — all additive

| Method | Path | Body | Success | Failure |
|---|---|---|---|---|
| POST | `/session/start` | `{"label": "Visitor 12"}` (optional / may be empty) | `201 {session_id, phase, label}` | `409 {error:"session_active", session_id}` |
| POST | `/session/end` | none | `200 {session_id, report_url, reliability}` | `409 {error:"no_active_session"}` |
| POST | `/session/calibration/restart` | none | `200 {session_id, attempts}` | `409 {error:"not_calibrating"}` |
| POST | `/session/intervention` | `{event, technique?, planned_duration_s?, cycles_completed?}` | `200 {status:"ok", index}` | `409 {error:"no_active_session"}` |
| GET | `/sessions` | — | `200 [ ... ]` newest first | — |
| GET | `/session/<id>/report` | — | `200 <report JSON>` | `404 {error:"not_found"}` |
| GET | `/session/<id>/report.html` | — | `200 text/html` attachment | `404` |
| GET | `/session/<id>/report.csv` | — | `200 text/csv` attachment | `404` |
| POST | `/session/exercise` | `{event}` | **KEEP** — back-compat alias forwarding to the intervention handler | — |

`/sessions` item shape:

```json
{ "id": "...", "label": "Visitor 12", "started_at_iso": "...", "duration_s": 374.0,
  "reliability": "GOOD", "peak_state": "ANXIETY", "episode_count": 1, "status": "final" }
```

Rules:

- `GET /session/<id>/report` for the **currently running** session returns the live partial with
  `status: "partial"` and `quality.reliability: "PARTIAL"`. Do not refuse it.
- `id` must be validated against `^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$` **before** touching the filesystem.
  Anything else -> 404. **No path traversal, ever.**
- `event` in `/session/intervention` must be `"start"` or `"stop"`; anything else -> `400`.
- All POST handlers are idempotent and safe to double-click.

---

## 4. EXECUTION PHASES

Each phase lists: **goal**, **files**, **exact work**, **acceptance checks**. Do not proceed until the
checks pass. After each phase, commit with the message given.

### Phase overview

| Phase | Goal | Delivers |
|---|---|---|
| **P1** | Session lifecycle skeleton | Start/End work; phase in snapshot; UI gating |
| **P2** | Calibration telemetry + coach | Honest progress; stall detection; restart |
| **P3** | Recorder + CSV v2 + live partial | Streaming aggregation; `session.live`; checkpoints |
| **P4** | Report intelligence | Episodes, warnings, provenance, reliability grade |
| **P5** | Backend-owned interventions | Durable intervention + recovery metrics |
| **P6** | Report view + downloads | In-app report, `/sessions`, HTML/CSV export |
| **P7** | Robustness + docs | `.partial.json` recovery, README, final regression |

---

## P1 — Session lifecycle skeleton

**Goal:** Start and End a session. Phase is server-authoritative and visible in the snapshot. Evaluation is
gated by phase. Browser refresh is transparent.

**Files:** `backend/paths.py` (add one function), `backend/config.py` (add dataclass),
`backend/session_manager.py` (new), `backend/state_service.py`, `backend/flask_app.py`,
`frontend/index.html`, `frontend/js/app.js`, `frontend/css/style.css`.

### P1.1 `backend/paths.py` — add exactly one function

```python
def sessions_dir() -> Path:
    return ensure_dir(data_dir() / "sessions")
```

### P1.2 `backend/config.py` — add a dataclass and one `AppConfig` field

```python
@dataclass
class SessionConfig:
    """Session lifecycle and reporting."""

    # Multiplier on calibration_seconds after which calibration is reported as stalled.
    calibration_stall_factor: float = field(
        default_factory=lambda: _env_float("ANXIETY_CALIB_STALL_FACTOR", 2.0)
    )
    # Seconds between .partial.json checkpoint writes.
    checkpoint_interval_s: float = field(
        default_factory=lambda: _env_float("ANXIETY_SESSION_CHECKPOINT_S", 10.0)
    )
    # Auto-start a session on boot (exhibition convenience). Default OFF.
    autostart: bool = field(
        default_factory=lambda: _env_bool("ANXIETY_SESSION_AUTOSTART", False)
    )
```

Then on `AppConfig`:

```python
    session: SessionConfig = field(default_factory=SessionConfig)
```

### P1.3 `backend/session_manager.py` — NEW

Pure state, no I/O, no locking of its own (the caller holds `AnxietyStateService._lock`).

```python
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
```

### P1.4 `backend/state_service.py` — the careful part

**(a) Imports and `__init__`.** Import `SessionManager` and the phase constants. In `__init__`, after the
existing subsystem construction, add:

```python
        self.sessions = SessionManager()
```

**(b) Add `session` to the snapshot.** Extend `DashboardSnapshot` with a new optional field
`session: Optional[Dict[str, Any]] = None`, and build the dict in `to_json_dict()` (not in `_on_sample`) so
elapsed time stays fresh even when no samples are arriving:

```python
    def _session_dict(self, now: float) -> Dict[str, Any]:
        """Build the `session` block. Caller must hold the lock."""
        st = self.sessions.state
        if st.phase == PHASE_IDLE:
            return {
                "phase": PHASE_IDLE, "id": None, "label": None, "started_at": None,
                "elapsed_s": 0.0, "monitored_s": 0.0,
                "recording": False, "evaluating": False,
                "calibration": None, "live": None,
            }
        return {
            "phase": st.phase,
            "id": st.id,
            "label": st.label,
            "started_at": st.started_at,
            "elapsed_s": round(st.elapsed_s(now), 1),
            "monitored_s": round(st.monitored_s(now), 1),
            "recording": st.recording,
            "evaluating": st.evaluating,
            "calibration": self._calibration_dict(now),   # returns None until P2
            "live": None,                                  # filled in P3
        }
```

In P1, `_calibration_dict()` may simply `return None`. P2 implements it.

`to_json_dict()` must take the lock, capture `now = time.time()`, and add
`"session": self._session_dict(now)` to the returned dict. **Do not remove or reorder existing keys.**

**(c) Gate evaluation in `_on_sample`.** Immediately after the two lines that set `self._snapshot.hr` and
`self._snapshot.gsr` from the raw sample, insert:

```python
            # Session gating: outside CALIBRATING/MONITORING we ingest and log raw
            # values (so the dashboard can act as a sensor check) but run no
            # evaluation and keep no session state.
            if not self.sessions.state.recording:
                self._maybe_log_csv(sample, None, None, None, None, None, None,
                                    self._snapshot.connection)
                return
```

**Important:** in the existing code `_maybe_log_csv` is called with the connection argument in some paths
and not others — match the existing signature exactly (it takes 8 positional args ending with
`connection`). Read the current signature before writing this call.

**(d) Detect the CALIBRATING -> MONITORING transition.** Inside `_on_sample`, right after
`self.baseline.update_with_sample(now, hr, gsr)`, add:

```python
            if self.baseline.is_ready() and self.sessions.phase == PHASE_CALIBRATING:
                self.sessions.mark_calibrated(now)
```

This is the only place the transition happens. Do not duplicate it.

**(e) Public session methods.** Add these to `AnxietyStateService`. Each takes `self._lock`.

```python
    def start_session(self, label: Optional[str] = None) -> Dict[str, Any]:
        """Start a fresh session. Returns {"ok": bool, ...}."""
        with self._lock:
            if self.sessions.state.active:
                return {"ok": False, "error": "session_active",
                        "session_id": self.sessions.state.id}
            now = time.time()
            self._reset_session_locked()          # see (f)
            st = self.sessions.start(label, now)
            self._snapshot.state = "CALM"
            self._snapshot.calibrated = False
            self._snapshot.features = None
            return {"ok": True, "session_id": st.id, "phase": st.phase, "label": st.label}

    def end_session(self) -> Dict[str, Any]:
        with self._lock:
            st = self.sessions.end(time.time())
            if st is None:
                return {"ok": False, "error": "no_active_session"}
            # P3 attaches report finalization here.
            return {"ok": True, "session_id": st.id, "reliability": None}

    def restart_calibration(self) -> Dict[str, Any]:
        with self._lock:
            if not self.sessions.restart_calibration(time.time()):
                return {"ok": False, "error": "not_calibrating"}
            self.pipeline.reset()
            self.baseline.reset()
            self._snapshot.calibrated = False
            self._snapshot.features = None
            return {"ok": True, "session_id": self.sessions.state.id,
                    "attempts": self.sessions.state.calibration_attempts}
```

**(f) Refactor `reset_session()` without changing its behavior.** Move its body into a new private
`_reset_session_locked()` (identical statements, no lock), and make the existing public `reset_session()`
just take the lock and call it. This keeps the public API intact while letting `start_session` reuse it.

```python
    def reset_session(self) -> None:
        with self._lock:
            self._reset_session_locked()

    def _reset_session_locked(self) -> None:
        # exact body of the current reset_session(), minus the `with self._lock:` line
        ...
```

**(g) Optional autostart.** In `start_reader()`, after `self._reader.start()`:

```python
        if self._cfg.session.autostart:
            self.start_session(label=None)
```

### P1.5 `backend/flask_app.py` — add three routes

Additive only; leave `/`, `/data`, `/stream`, `/session/exercise` untouched.

```python
    @app.route("/session/start", methods=["POST"])
    def session_start():
        payload = request.get_json(silent=True) or {}
        res = service.start_session(label=payload.get("label"))
        if not res.get("ok"):
            return jsonify({"error": res.get("error"),
                            "session_id": res.get("session_id")}), 409
        return jsonify({"session_id": res["session_id"], "phase": res["phase"],
                        "label": res["label"]}), 201

    @app.route("/session/end", methods=["POST"])
    def session_end():
        res = service.end_session()
        if not res.get("ok"):
            return jsonify({"error": res.get("error")}), 409
        return jsonify({
            "session_id": res["session_id"],
            "report_url": "/session/" + res["session_id"] + "/report",
            "reliability": res.get("reliability"),
        })

    @app.route("/session/calibration/restart", methods=["POST"])
    def session_calibration_restart():
        res = service.restart_calibration()
        if not res.get("ok"):
            return jsonify({"error": res.get("error")}), 409
        return jsonify({"session_id": res["session_id"], "attempts": res["attempts"]})
```

### P1.6 `frontend/index.html` — session controls

Add into `<div class="header-actions">`, **before** the existing `#calibratedPill` button:

```html
          <div class="session-controls" id="sessionControls">
            <span class="session-chip" id="sessionChip" hidden>
              <span class="session-chip-dot" aria-hidden="true"></span>
              <span class="session-chip-label" id="sessionChipLabel">Session</span>
              <span class="session-chip-time" id="sessionChipTime">00:00</span>
            </span>
            <button type="button" class="btn btn-primary session-btn" id="sessionPrimaryBtn">
              Start Session
            </button>
            <button type="button" class="btn btn-ghost session-btn" id="sessionsListBtn" hidden>
              Sessions
            </button>
          </div>
```

Add a start dialog near the existing breathing modal markup (reuse the existing
`.breathing-modal-backdrop` / `.breathing-modal` class pattern so it inherits the current styling):

```html
      <div class="breathing-modal-backdrop" id="sessionStartBackdrop" hidden></div>
      <div class="breathing-modal session-start-modal" id="sessionStartModal"
           role="dialog" aria-modal="true" aria-labelledby="sessionStartTitle" hidden>
        <div class="bm-header">
          <h2 id="sessionStartTitle">Start a monitoring session</h2>
          <button type="button" class="guide-close" id="sessionStartCloseBtn"
                  aria-label="Cancel">&times;</button>
        </div>
        <div class="bm-body">
          <p class="session-start-copy">
            A fresh personal baseline will be measured for this person. Nothing from a previous
            session carries over.
          </p>
          <label class="session-label-field">
            <span>Name or label (optional)</span>
            <input type="text" id="sessionLabelInput" maxlength="64"
                   placeholder="e.g. Visitor 12" autocomplete="off" />
          </label>
          <button type="button" class="btn btn-primary btn-start-exercise"
                  id="sessionStartConfirmBtn">Start session</button>
        </div>
      </div>
```

### P1.7 `frontend/js/app.js` — phase-driven gating

**Rule: `render(d)` stays pure.** The only client state allowed is transient UI state (dialog open, last
seen phase for one-shot actions).

Add DOM refs alongside the existing ones, then:

```javascript
// ── Feature: Session lifecycle ───────────────────────────────────────────────
let sessionPhase = "IDLE";          // mirror of d.session.phase, for click handling only
let lastSessionId = null;

function fmtClock(totalSec) {
  var s = Math.max(0, Math.round(totalSec));
  var m = Math.floor(s / 60);
  return String(m).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

function updateSessionControls(d) {
  var sess = d.session || { phase: "IDLE" };
  sessionPhase = sess.phase;
  lastSessionId = sess.id || lastSessionId;

  if (SESSION_PRIMARY_BTN) {
    if (sess.phase === "IDLE")            SESSION_PRIMARY_BTN.textContent = "Start Session";
    else if (sess.phase === "ENDED")      SESSION_PRIMARY_BTN.textContent = "Start New Session";
    else                                  SESSION_PRIMARY_BTN.textContent = "End Session";
    SESSION_PRIMARY_BTN.classList.toggle("is-danger", sess.recording === true);
  }
  if (SESSION_CHIP) {
    SESSION_CHIP.hidden = (sess.phase === "IDLE");
    if (SESSION_CHIP_LABEL) SESSION_CHIP_LABEL.textContent = sess.label || "Unlabelled session";
    if (SESSION_CHIP_TIME)  SESSION_CHIP_TIME.textContent = fmtClock(sess.elapsed_s || 0);
    SESSION_CHIP.classList.toggle("is-recording", sess.recording === true);
  }
  document.body.classList.toggle("session-idle", sess.phase === "IDLE");
  document.body.classList.toggle("session-ended", sess.phase === "ENDED");
}
```

Primary button handler:

```javascript
if (SESSION_PRIMARY_BTN) {
  SESSION_PRIMARY_BTN.addEventListener("click", function () {
    if (sessionPhase === "IDLE" || sessionPhase === "ENDED") {
      openSessionStartModal();
    } else {
      if (!confirm("End this monitoring session and generate its report?")) return;
      SESSION_PRIMARY_BTN.disabled = true;
      fetch("/session/end", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (j) { if (j.session_id) onSessionEnded(j.session_id); })
        .catch(function (e) { console.error("end session:", e); })
        .then(function () { SESSION_PRIMARY_BTN.disabled = false; });
    }
  });
}
```

Start confirm handler posts `{label: input.value}` to `/session/start`, closes the dialog on 201, and shows
the server's message on 409. `onSessionEnded(id)` is a stub in P1 (`console.log`) — P6 implements it.

**Gating inside `render(d)`** — add `updateSessionControls(d)` as the first call, then:

- If `d.session.phase === "IDLE"`: still render HR, GSR, connection, and the chart (sensor check), but
  set the state card to a "Not monitoring" presentation, hide the prediction strip and the breathing
  prompt, and skip `setCalibrationStatus`-driven calibration copy. Implement as one guard near the top:

```javascript
  var recording = d.session && d.session.recording === true;
  if (!recording) {
    if (STATE_EL) { STATE_EL.textContent = "IDLE"; STATE_EL.classList.add("state--compact"); }
    if (BP_PROMPT) BP_PROMPT.style.display = "none";
    if (PRED_BANNER) PRED_BANNER.style.display = "none";
  }
```

- Wrap the existing breathing-prompt block so it only runs when `recording` is true.
- Leave the HR/GSR/chart code paths exactly as they are.

### P1.8 `frontend/css/style.css`

Append at the **end of the file** (never edit existing rules) styles for `.session-controls`,
`.session-chip`, `.session-chip-dot` (pulsing when `.is-recording`), `.session-btn`,
`.session-start-modal`, `.session-label-field`, and `.btn.is-danger`. Reuse the existing CSS custom
properties (`--calm`, `--stress`, `--anxiety`, `--recovery`, `--bg-base`) — do not introduce new colour
literals where a token exists.

### P1 acceptance checks

1. `$env:ANXIETY_USE_MOCK_SERIAL=1; python app.py` starts clean.
2. `GET /data` contains `session.phase == "IDLE"` **and** every field from Section 1.3.
3. On load, the header shows **Start Session**; HR/GSR update; the state card reads `IDLE`; no prediction
   strip; no breathing prompt.
4. `POST /session/start` with `{"label":"Test A"}` -> `201`. Snapshot flips to `CALIBRATING`; the chip shows
   `Test A` with a running clock.
5. After the calibration window, snapshot flips to `MONITORING` **by itself**; live prediction resumes
   exactly as before this phase.
6. `POST /session/start` again while running -> `409 {"error":"session_active", ...}` and **no** new
   session id.
7. `POST /session/end` -> `200`; phase becomes `ENDED`; the button reads **Start New Session**.
8. `POST /session/end` again -> `409 {"error":"no_active_session"}`.
9. Start a second session -> a **different** `session.id`, `calibrated` returns to `false`, and
   `baseline_hr`/`baseline_gsr` are re-measured (not carried over).
10. **Refresh the browser mid-session** -> the UI comes back in the correct phase with the correct label and
    elapsed time, with no manual action.
11. `service.reset_session()` still exists and still works (call it from a Python REPL or leave it unused).

**Commit:** `feat(session): add server-authoritative session lifecycle (P1)`

---

## P2 — Calibration telemetry and coach

**Goal:** Honest calibration progress, stall detection with actionable copy, and in-session calibration
restart. Fixes F-D and F-E.

**Files:** `backend/features.py`, `backend/state_service.py`, `frontend/js/app.js`,
`frontend/index.html`, `frontend/css/style.css`.

### P2.1 `backend/features.py` — additive telemetry on `BaselineTracker`

Do **not** change `update_with_sample()`'s locking logic or `compute_features()`. Only record extra state
and expose it.

In `__init__`, add:

```python
        self._calib_started_t: Optional[float] = None
        self._last_span: float = 0.0
        self._last_stable: bool = False
        self._locked_at_t: Optional[float] = None
        self._locked_after_s: Optional[float] = None
```

In `reset()`, clear all five back to their initial values.

Inside `update_with_sample()`, in the calibration branch only:

- The first time a sample is appended, set `self._calib_started_t = t` if it is `None`.
- After computing `span`, store `self._last_span = span`.
- After the std checks, store `self._last_stable = (std_hr <= self._max_std_hr and std_gsr <= self._max_std_gsr)`.
- When the baseline locks, set `self._locked_at_t = t` and
  `self._locked_after_s = t - self._calib_started_t` (guard for `None`).

Add public accessors:

```python
    @property
    def calibration_target_s(self) -> float:
        return self._calib_s

    @property
    def calibration_method(self) -> str:
        """"fixed" when a configured baseline is used, else "personalized"."""
        return "fixed" if (self._fixed_hr is not None and self._fixed_gsr is not None) else "personalized"

    def calibration_elapsed_s(self, now_t: float) -> float:
        if self.calibration_method == "fixed":
            return 0.0
        if self._locked_after_s is not None:
            return self._locked_after_s
        if self._calib_started_t is None:
            return 0.0
        return max(0.0, now_t - self._calib_started_t)

    def calibration_progress(self) -> float:
        """0.0-1.0 from the true buffer span, NOT the sliding prediction window."""
        if self.is_calibrated:
            return 1.0
        if self._calib_s <= 0:
            return 1.0
        return max(0.0, min(1.0, self._last_span / self._calib_s))

    @property
    def calibration_stable(self) -> bool:
        """Did the most recently evaluated buffer pass the stability gates."""
        return self._last_stable

    def calibration_locked_after_s(self) -> Optional[float]:
        return self._locked_after_s
```

### P2.2 `backend/state_service.py` — implement `_calibration_dict`

Replace the P1 stub:

```python
    def _calibration_dict(self, now: float) -> Optional[Dict[str, Any]]:
        """Calibration telemetry for the `session` block. Caller holds the lock."""
        st = self.sessions.state
        if st.phase == PHASE_IDLE:
            return None
        b = self.baseline
        target = b.calibration_target_s
        elapsed = b.calibration_elapsed_s(now)
        conn = (self._snapshot.connection or "").lower()
        paused = st.phase == PHASE_CALIBRATING and conn not in ("connected", "mock")
        stall_after = target * self._cfg.session.calibration_stall_factor
        stalled = (
            st.phase == PHASE_CALIBRATING
            and not paused
            and elapsed > stall_after
        )
        return {
            "method": b.calibration_method,
            "progress": round(b.calibration_progress(), 3),
            "elapsed_s": round(elapsed, 1),
            "target_s": target,
            "stable": bool(b.calibration_stable),
            "stalled": bool(stalled),
            "paused": bool(paused),
            "attempts": st.calibration_attempts,
        }
```

`restart_calibration()` already exists from P1.4(e). Verify it resets `pipeline` and `baseline` so the
telemetry restarts from zero.

### P2.3 `frontend/js/app.js` — drive the ring from real progress

1. **Delete the `window_samples`-based progress computation.** Replace the `calProgress` calculation in
   `render(d)` with `d.session.calibration.progress`. Keep `CALIBRATION_TARGET_SAMPLES` removal local — if
   the constant becomes unused, remove the constant too.
2. Extend `setCalibrationStatus(d)` with a stalled/paused branch, **before** the existing
   `!calibrated` branch:

```javascript
  var cal = (d.session && d.session.calibration) || null;
  if (cal && cal.paused) {
    CAL_TITLE.textContent = "Calibration paused — sensor not sending data";
    CAL_MESSAGE.textContent = "Check the sensor contact and the Bluetooth link. "
      + "Calibration will resume automatically; nothing measured so far is lost.";
    CAL_STATUS.textContent = "Paused";
  } else if (cal && cal.stalled) {
    CAL_TITLE.textContent = "Still looking for a steady baseline";
    CAL_MESSAGE.textContent = "Signal variation is too high to lock a baseline. "
      + "Rest your hand flat, stop talking, and stay still for about 30 seconds.";
    CAL_STATUS.textContent = "Hold still";
  }
```

3. Show a **Restart calibration** button only when `cal && cal.stalled`; `POST` to
   `/session/calibration/restart`, then hide it.
4. Show `Math.round(cal.progress * 100)` in `#stateCalibratingPct`, and when
   `cal.method === "fixed"` display "Using configured baseline" instead of a progress percentage.

### P2 acceptance checks

1. During calibration in mock mode, the ring climbs smoothly and reaches 100% **only when the baseline
   actually locks** — it must not sit at 100% while still calibrating.
2. `session.calibration.elapsed_s` increases once per second; `progress` matches the ring.
3. Set `ANXIETY_BASELINE_CALIBRATION_S=5` and `ANXIETY_CALIB_STALL_FACTOR=1.2`, then start a session while
   the mock generator is in its noisy phase -> `stalled` becomes `true` and the "hold still" copy appears.
4. Clicking **Restart calibration** returns `progress` to ~0 and increments `attempts`; the session id is
   **unchanged**.
5. With both `ANXIETY_FIXED_BASELINE_HR` and `ANXIETY_FIXED_BASELINE_GSR` set, a new session goes
   `CALIBRATING -> MONITORING` almost immediately and `method` is `"fixed"`.
6. Live monitoring after calibration is unchanged.

**Commit:** `feat(session): honest calibration telemetry and stall coaching (P2)`

---

## P3 — Session recorder, CSV v2, live partial

**Goal:** Stream-aggregate everything the report needs, expose `session.live`, write checkpoints, and
attribute every CSV row to a session.

**Files:** `backend/session_recorder.py` (new), `backend/state_service.py`.

### P3.1 `backend/session_recorder.py` — NEW

The recorder is **fed**, it does not pull. One `observe()` call per evaluated sample. O(1) memory for
aggregates; event lists are capped at `MAX_EVENT_ITEMS`.

Required public surface:

```python
class SessionRecorder:
    def __init__(self, session_id: str, label: Optional[str], started_at: float,
                 target_calibration_s: float) -> None: ...

    # --- ingestion -------------------------------------------------------
    def observe(self, *, now: float, phase: str, hr: Optional[float], gsr: Optional[float],
                state: Optional[str], rule_state: Optional[str], ml_state: Optional[str],
                fused_state: Optional[str], fusion_source: Optional[str],
                pattern: Optional[str], alert: Optional[str],
                features: Optional[Dict[str, float]], prediction: Optional[Dict[str, Any]],
                connection: Optional[str]) -> None: ...

    def note_rejected_sample(self) -> None: ...
    def note_calibrated(self, now: float, baseline_hr: Optional[float],
                        baseline_gsr: Optional[float], method: str,
                        locked_after_s: Optional[float], attempts: int) -> None: ...
    def note_calibration_restart(self) -> None: ...

    # --- interventions (P5 fills the body; define the methods in P3) -----
    def intervention_start(self, now: float, technique: str,
                           planned_duration_s: Optional[int]) -> int: ...
    def intervention_stop(self, now: float, cycles_completed: Optional[int],
                          aborted: bool = False) -> None: ...

    # --- output ----------------------------------------------------------
    def live_summary(self, now: float) -> Dict[str, Any]: ...
    def build_report(self, now: float, *, status: str, end_reason: Optional[str],
                     terminal_state: Optional[str], terminal_phase: str) -> Dict[str, Any]: ...
```

Internal accumulator groups (all plain attributes, no external state):

- **Counters:** `samples_evaluated`, `samples_rejected`, `conf_sum`, `conf_min`,
  `low_conf_samples`, `unstable_samples`.
- **Physiology running stats:** `hr_sum/min/max/last`, `gsr_sum/min/max/last`,
  `peak_delta_hr`, `peak_delta_gsr`, `peak_stress_index`, `stress_sum`,
  `peak_deviation_at_rel`.
- **State accounting:** `current_state`, `current_state_since`, `state_seconds: Dict[str, float]`,
  `transitions: List[dict]`. Accumulate by **elapsed time between observations**, not by sample count, so
  gaps do not inflate durations:

```python
        dt = now - self._last_observe_t if self._last_observe_t else 0.0
        if 0.0 < dt <= DISCONNECT_GAP_S:
            self.state_seconds[state] = self.state_seconds.get(state, 0.0) + dt
```

- **Gap / disconnect detection:** if `dt > DISCONNECT_GAP_S`, append
  `{"at_rel": <rel of gap start>, "duration_s": round(dt, 1)}` to `disconnections`. Time inside a gap is
  attributed to **no** state.
- **Alerts:** rising-edge counts per level, `peak_alert`, `seconds_at_high` (accumulated the same `dt` way).
- **Provenance:** `fusion_source_counts`, `ml_anxiety_adoptions` (increment when
  `fused_state == "ANXIETY" and fusion_source in ("ml", "both")`), `rule_final_agree`,
  `smoothing_suppressed_flips` (increment when `fused_state` changed since the previous observation **but**
  `state` did not).
- **Patterns:** `pattern_counts`.
- **Warnings / episodes:** raw event lists in P3; the derivation logic lands in P4. In P3, record the raw
  rising edges:

```python
        active = bool(prediction and prediction.get("active"))
        if active and not self._prev_prediction_active:
            self._warning_events.append({
                "at_rel": rel, "at_abs": now,
                "predicted_state": prediction.get("predicted_state"),
                "forecast_s": prediction.get("seconds_to_transition"),
                "basis": prediction.get("basis"),
                "outcome": None, "actual_lead_time_s": None,
            })
        self._prev_prediction_active = active
```

**Rules the recorder must obey:**

- Only observations where `phase == "MONITORING"` contribute to `physiology`, `states`, `episodes`,
  `alerts`, `early_warnings`, and `provenance`. Observations during `CALIBRATING` contribute only to
  `quality` (sample counts, connection gaps).
- `rel` (relative time) is always `now - calibrated_at` when a baseline exists, else `now - started_at`.
  Store `self._monitor_t0` when `note_calibrated` fires and use it consistently.
- Every event list append must be guarded: `if len(lst) < MAX_EVENT_ITEMS: lst.append(...)`.
- `observe()` must never raise. Wrap the body in `try/except Exception` and `LOG.debug` on failure
  (see F-O).

`live_summary(now)` returns the small dict for `session.live` in §3.3 — reliability computed with the
§3.5 rules against the numbers so far, `PARTIAL` never applied here (use the real grade so the presenter
can see quality drifting).

`build_report()` assembles §3.4. In P3 it may emit `episodes: []`, `early_warnings` with
`outcome: null`, and a one-line `narrative` — P4 completes them.

### P3.2 `backend/state_service.py` — wire it up

**(a) Own the recorder.** Add `self._recorder: Optional[SessionRecorder] = None`.
`start_session()` constructs one; `end_session()` finalizes and clears it.

**(b) Feed it from `_on_sample`.** After the snapshot is rebuilt, **outside** the existing
evaluation `try/except`, add:

```python
            if self._recorder is not None:
                try:
                    self._recorder.observe(
                        now=now,
                        phase=self.sessions.phase,
                        hr=hr, gsr=gsr,
                        state=final_state, rule_state=rule_state, ml_state=ml_state,
                        fused_state=self._snapshot.fused_state,
                        fusion_source=self._snapshot.fusion_source,
                        pattern=pattern_type, alert=alert_level,
                        features=feat_map, prediction=self._snapshot.prediction,
                        connection=self._snapshot.connection,
                    )
                except Exception as e:
                    LOG.debug("recorder observe: %s", e)
```

Also call `self._recorder.note_rejected_sample()` on the early-return paths where `pipeline.push()` or
`compute_features()` returned `None` during a recording phase, and `note_calibrated(...)` at the
`mark_calibrated` site from P1.4(d).

**(c) Checkpointing.** In `_on_sample`, after `observe`, throttled by
`self._cfg.session.checkpoint_interval_s`, write
`sessions_dir() / (session_id + ".partial.json")` with
`build_report(now, status="partial", ...)`. **Write to a `.tmp` file and `os.replace()`** so a crash can
never leave truncated JSON.

**(d) Finalize on end.** In `end_session()`:

1. `report = self._recorder.build_report(now, status="final", end_reason=st.end_reason, terminal_state=self._snapshot.state, terminal_phase="ENDED")`
2. Write `sessions_dir() / (id + ".json")` via the same tmp+replace pattern.
3. Delete the `.partial.json` if present (swallow errors).
4. Return `{"ok": True, "session_id": id, "reliability": report["quality"]["reliability"]}`.
5. `self._recorder = None`.

Do the JSON writing **outside** the lock if practical: build the dict under the lock, release, then write.
If that is awkward, keep it inside — the file is small (<100 KB) — but add a `# NOTE(plan):` comment.

**(e) `session.live`.** In `_session_dict`, replace `"live": None` with
`self._recorder.live_summary(now) if self._recorder else None`. In `ENDED`, keep the last computed summary
in an instance attribute (`self._last_live_summary`) so the UI still has numbers after the recorder is
cleared.

**(f) CSV v2.** Implement §3.7: new `fieldnames`, the rotation check, and `session_id` / `session_phase` on
every row in both `_maybe_log_csv()` and `log_exercise_event()`.

### P3 acceptance checks

1. A full mock session start -> calibrate -> ~90 s monitoring -> end produces
   `data/sessions/<id>.json` with populated `identity`, `quality`, `baseline`, `physiology`, `states`,
   `provenance`.
2. `data/logs/physio_log.csv` has the v2 header; the old file is now
   `data/logs/physio_log.pre_sessions.csv`. Rows during a session carry the `session_id`; rows in `IDLE`
   carry an empty `session_id`.
3. `session.live` appears in `/data` during monitoring and its `coverage_pct` is plausible (>90% in mock).
4. `sum(states.seconds.values())` is within ~5% of `monitored_duration_s`.
5. A `.partial.json` appears within ~10 s of monitoring starting and is **gone** after a clean end.
6. `states.seconds` never exceeds `monitored_duration_s` (gap attribution is correct).
7. Live monitoring performance is unaffected — the dashboard still updates once per second with no lag.

**Commit:** `feat(session): streaming session recorder, CSV v2, live partial (P3)`

---

## P4 — Report intelligence

**Goal:** Episodes, verified early warnings, reliability grading, and the deterministic narrative.

**Files:** `backend/session_recorder.py`, `backend/report_render.py` (new).

### P4.1 Episode detection

Track episodes **incrementally** from FSM state changes, never from `rule_state`.

```
On each observed state change (from -> to), at rel time `r`:
  if `from` in ("STRESS", "ANXIETY"):
      close the open episode:
          duration_s = r - open.start_rel
          if duration_s >= EPISODE_MIN_DURATION_S: keep it; else discard
          resolved_via = "RECOVERY" if `to` == "RECOVERY"
                         else "direct_calm" if `to` == "CALM"
                         else None   # STRESS -> ANXIETY is an escalation, see below
  if `to` in ("STRESS", "ANXIETY"):
      open a new episode { kind: to, start_rel: r, ... }
```

Escalation rule: `STRESS -> ANXIETY` **closes** the STRESS episode and **opens** an ANXIETY one. Set the
closed STRESS episode's `resolved_via` to `"direct_calm"` only if it actually went to CALM; for an
escalation, set it to `null` and add the string `"escalated"` to its `patterns_observed`. Keep this simple
and document the choice with a `# NOTE(plan):` comment.

While an episode is open, update `peak_stress_index`, `peak_hr`, `peak_delta_gsr`,
`max_alert_reached` (use the ordering `NONE < LOW < MEDIUM < HIGH`), and add unique non-`NORMAL` patterns
to `patterns_observed`.

At session end, any still-open episode is closed with `resolved_via = "open_at_session_end"` and kept if it
meets the minimum duration. **Never synthesize a resolution.**

`preceded_by_early_warning` / `lead_time_s`: when an episode opens, scan `_warning_events` backwards for the
most recent warning whose `predicted_state == episode.kind` and whose `at_rel` is within
`forecast_s + WARNING_GRACE_S` before the episode start. If found, set both fields and mark that warning
`outcome = "confirmed"` with `actual_lead_time_s = episode.start_rel - warning.at_rel`.

`intervention_index`: set when an intervention's `[start, start + actual_duration]` window overlaps the
episode's `[start_rel, start_rel + duration_s]` window.

### P4.2 Early-warning verification

At report build time, any warning still `outcome == None` becomes `"unconfirmed"`.
`median_lead_time_s` is the median of `actual_lead_time_s` across confirmed warnings (use
`statistics.median`; `None` when there are none).

**Wording rule:** report as *"N warnings issued, M confirmed"*. **Never** compute or label this an
accuracy, precision, or validation figure.

### P4.3 Reliability grading

Implement §3.5 verbatim as a function:

```python
def grade_reliability(*, baseline_completed: bool, monitored_duration_s: float,
                      coverage_pct: float, mean_confidence: float) -> tuple[str, list[str]]:
```

Then apply the §3.5 rendering consequences inside `build_report()` — for `INSUFFICIENT`, null out the
sections and populate `unavailable`.

### P4.4 `backend/report_render.py` — NEW

Two public functions. **Stdlib only. No LLM. No template engine.**

```python
def build_narrative(report: Dict[str, Any]) -> List[str]:
    """Deterministic 5-8 sentence summary assembled from report fields."""

def render_html(report: Dict[str, Any]) -> str:
    """Standalone, self-contained HTML document (inline CSS, no external assets)."""
```

`build_narrative` rules — emit sentences in this order, skipping any whose inputs are `null`:

1. Identity + duration: label (or "Unlabelled session"), total duration, monitored duration.
2. Baseline: `"A personal baseline of HR {hr} bpm and GSR {gsr} was measured over {n} s."` — when
   `method == "fixed"`, say `"A configured (non-personalized) baseline was used."` instead.
3. Reliability: the grade plus its reasons, in plain language.
4. Time in state: the dominant state and its percentage.
5. Episodes: count and the longest episode's kind/duration/peak — **or**, when zero:
   `"No stress or anxiety episodes were detected; the session remained in CALM for {pct}% of the monitored window."`
6. Early warnings: `"{issued} early warnings were issued; {confirmed} were followed by the predicted state within the forecast window."`
7. Interventions: per-intervention observational sentence, **or**
   `"No breathing exercise was performed during this session."`
8. Provenance: `"{rules}% of decisions came from the rule engine, {ml}% involved the ML model; the smoothing and state-machine layers suppressed {n} unstable label flips."`

Every sentence must be **descriptive, not causal**. Approved verbs: *was measured*, *was recorded*,
*decreased*, *increased*, *remained*, *was observed*, *was detected*. Banned: *caused*, *reduced stress*,
*treated*, *cured*, *improved anxiety*, *diagnosed*, *indicates a disorder*, *is healthy/unhealthy*.

`render_html` must produce a single file that opens offline: inline `<style>`, no CDN references, no
JavaScript required to read it. Sections in report order (reliability banner first). It must render
`null` fields as *"not available — {reason}"*. HTML-escape every interpolated value with
`html.escape()`.

### P4 acceptance checks

1. Run a mock session long enough to hit the mock generator's stress cycle. The report contains at least
   one episode with a plausible `duration_s`, `peak_hr`, and `max_alert_reached`.
2. Every episode's `duration_s >= 5.0`.
3. `episode_count == len(episodes)` and equals `stress_episode_count + anxiety_episode_count`.
4. At least one warning has `outcome` set to `"confirmed"` or `"unconfirmed"` — never `null` in a final
   report.
5. End a session while in `ANXIETY` -> the last episode has `resolved_via == "open_at_session_end"` and
   `identity.terminal_state == "ANXIETY"`.
6. A session ended after 20 s -> `reliability == "INSUFFICIENT"`, `reliability_reasons` non-empty,
   `physiology` and `states` are `null`, and `unavailable` explains why.
7. A calm-only session -> `episode_count == 0` and the narrative states this as a normal result, not an
   error.
8. `build_narrative` output contains no banned verb from §6.
9. `render_html` output contains no `http://` or `https://` asset reference.

**Commit:** `feat(report): episodes, warning verification, reliability grading, narrative (P4)`

---

## P5 — Backend-owned interventions and recovery

**Goal:** The intervention record survives a page refresh and recovery metrics come from the sample stream.

**Files:** `backend/session_recorder.py`, `backend/state_service.py`, `backend/flask_app.py`,
`frontend/js/app.js`.

**Division of responsibility (do not change this):** the **browser keeps** the box-breathing animation,
the phase timer, the cycle counter, and the modal. The **backend gains** the record and the physiological
sampling, because `_on_sample` already sees every reading.

### P5.1 Recorder

Implement the bodies of `intervention_start` / `intervention_stop`, and extend `observe()` to sample the
active intervention and its recovery window.

- `intervention_start(now, technique, planned_duration_s)`: append a record with `index` (1-based),
  `started_at_rel`, `state_at_start`, `hr_at_start`, `gsr_at_start`, `stress_index_at_start` taken from the
  most recent observation. Return the index. Set `self._active_intervention = idx`.
- While an intervention is active, accumulate `hr` values for `hr_mean_during`.
- `intervention_stop(now, cycles_completed, aborted=False)`: set `actual_duration_s`, `hr_at_end`,
  `gsr_at_end`, `state_at_end`, `stress_index_at_end`, `hr_change_bpm`, `hr_change_pct`, `gsr_change`,
  `cycles_completed`, and `completion`:
  - `"aborted_by_session_end"` when `aborted` is True
  - `"stopped_early"` when `actual_duration_s < planned_duration_s * 0.9`
  - otherwise `"completed"`
  Then open the recovery window: `self._recovery_until = now + RECOVERY_WINDOW_S`.
- While inside the recovery window, `observe()` updates the record: set `entered_recovery_within_window`
  if `state == "RECOVERY"`, and `returned_to_calm_within_window` + `time_to_calm_s` on the **first**
  `state == "CALM"`.
- When the window closes naturally, set `hr_at_plus_60s` to the last observed HR and
  `recovery_data = "available"`.
- If the session ends while the window is open: `recovery_data = "truncated"`, `hr_at_plus_60s = null`,
  plus an `unavailable` entry `"interventions[i].hr_at_plus_60s": "session ended before the 60 s recovery window completed"`.
- If fewer than 5 observations landed in the window: `recovery_data = "unavailable"`.

`intervention_summary`: `count`, `n_with_hr_reduction` (`hr_change_bpm < 0`),
`median_hr_change_bpm` (`statistics.median`, `null` when empty).

### P5.2 Service + route

```python
    def log_intervention(self, event: str, *, technique: str = "box_4_4_4_4",
                         planned_duration_s: Optional[int] = None,
                         cycles_completed: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            if not self.sessions.state.recording or self._recorder is None:
                return {"ok": False, "error": "no_active_session"}
            now = time.time()
            if event == "start":
                idx = self._recorder.intervention_start(now, technique, planned_duration_s)
            else:
                self._recorder.intervention_stop(now, cycles_completed)
                idx = self._recorder.intervention_count
            self._write_exercise_csv_row_locked(event)     # reuse existing CSV marker logic
            return {"ok": True, "index": idx}
```

Keep `log_exercise_event()` working (extract its CSV-writing body into
`_write_exercise_csv_row_locked(event)` and have both callers use it) so `POST /session/exercise` remains
functional.

Route:

```python
    @app.route("/session/intervention", methods=["POST"])
    def session_intervention():
        payload = request.get_json(silent=True) or {}
        event = str(payload.get("event", "")).lower()
        if event not in ("start", "stop"):
            return jsonify({"error": "invalid_event"}), 400
        res = service.log_intervention(
            event,
            technique=str(payload.get("technique") or "box_4_4_4_4"),
            planned_duration_s=payload.get("planned_duration_s"),
            cycles_completed=payload.get("cycles_completed"),
        )
        if not res.get("ok"):
            return jsonify({"error": res.get("error")}), 409
        return jsonify({"status": "ok", "index": res.get("index")})
```

`POST /session/exercise` stays as-is but forwards to `service.log_intervention(event)` so both paths record.

### P5.3 `end_session()` must abort an open intervention

Before building the report, if an intervention is still active, call
`self._recorder.intervention_stop(now, cycles_completed=None, aborted=True)`.

### P5.4 Frontend

- `logExerciseBackend(event)` becomes a richer call to `/session/intervention` carrying `technique`
  (`"box_4_4_4_4"`), `planned_duration_s` (`exerciseDurationSec`), and `cycles_completed`
  (`exerciseCycleCount`).
- Keep `exerciseBuffer` and the existing recovery card **exactly as they are** — they give instant local
  feedback. The backend record is the durable one; they can coexist.
- Disable the breathing FAB and suppress the breathing prompt when `d.session.recording !== true`.

### P5 acceptance checks

1. Run a 60 s breathing exercise during a mock session; end the session. The report's `interventions[0]`
   has `completion == "completed"`, non-null `hr_at_start` / `hr_at_end` / `hr_change_bpm`, and
   `recovery_data == "available"`.
2. Stop the exercise after ~15 s -> `completion == "stopped_early"`.
3. End the **session** during the exercise -> `completion == "aborted_by_session_end"` and
   `recovery_data` is `"truncated"` or `"unavailable"`.
4. End the session ~10 s after the exercise finishes -> `recovery_data == "truncated"`,
   `hr_at_plus_60s` is `null`, and `unavailable` explains it.
5. Refresh the browser mid-exercise -> the **backend** still has the intervention record in the final
   report (the browser's local recovery card resetting is expected and acceptable).
6. `POST /session/exercise` still returns 200 and still writes its CSV marker row.
7. The existing in-modal recovery summary card still renders as before.

**Commit:** `feat(session): backend-owned interventions with recovery metrics (P5)`

---

## P6 — Report view and downloads

**Goal:** Read the report in the app; download it; browse past sessions.

**Files:** `backend/flask_app.py`, `frontend/index.html`, `frontend/js/app.js`,
`frontend/css/style.css`.

### P6.1 Routes

```python
import re
_SESSION_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
```

- `GET /sessions` — list `sessions_dir()` for `*.json` (excluding `*.partial.json`), read each, project the
  §3.9 item shape, sort by `started_at_iso` descending, cap at 50. Skip unreadable files (log at debug).
- `GET /session/<sid>/report` — validate `sid` against `_SESSION_ID_RE` first (else 404). If `sid` is the
  **currently running** session, return `service.build_partial_report()`. Otherwise read
  `<sid>.json`, falling back to `<sid>.partial.json` (which reports `status: "interrupted"`). 404 if
  neither exists.
- `GET /session/<sid>/report.html` — same lookup, then `report_render.render_html(report)` with
  `Content-Type: text/html` and `Content-Disposition: attachment; filename="saarthi-<sid>.html"`.
- `GET /session/<sid>/report.csv` — stream `data/logs/physio_log.csv` filtered to rows whose `session_id`
  matches, preserving the header. Use `csv.DictReader` / `DictWriter` over an `io.StringIO`. If no rows
  match, return the header alone (200, not 404).

Add `build_partial_report()` to the service: takes the lock, returns
`self._recorder.build_report(time.time(), status="partial", end_reason=None, terminal_state=self._snapshot.state, terminal_phase=self.sessions.phase)`
with `quality.reliability` forced to `"PARTIAL"`, or `None` if there is no recorder.

### P6.2 Report panel

Add one `<section class="report-panel" id="reportPanel" hidden>` after the existing `.chart-wrap` section.
It **replaces** the live grid when shown (toggle a `body.report-open` class that hides `.cards` and
`.chart-wrap` via CSS) — **no blocking modal**.

Panel structure, in this order:

1. Header: label, date, duration, a **Start New Session** button, a close button.
2. **Reliability banner** — grade + reasons, colour-keyed (`GOOD` -> `--calm`, `LIMITED` -> `--stress`,
   `INSUFFICIENT` / `PARTIAL` -> neutral/grey). This comes **first**, before any metric.
3. Narrative paragraph list.
4. Baseline + physiology stat grid (reuse the existing `.rc-stat` markup pattern).
5. **State timeline** — a horizontal band of `<div>` segments sized by percentage and coloured with the
   existing `--calm` / `--stress` / `--anxiety` / `--recovery` tokens, with a legend showing seconds and
   percentages. Plain CSS flexbox; **no Chart.js needed**. This is the report's hero visual.
6. Episode cards.
7. Early warnings (issued / confirmed) — labelled exactly *"issued"* and *"confirmed"*.
8. Interventions.
9. Provenance.
10. Download row: **JSON**, **HTML**, **CSV** links.
11. Method notes + the `disclaimer` string verbatim.

Add a **Sessions** drawer listing `/sessions` results; clicking one loads that report into the same panel.

### P6.3 JS

```javascript
function onSessionEnded(sessionId) {
  fetch("/session/" + sessionId + "/report")
    .then(function (r) { return r.json(); })
    .then(function (rep) { renderReport(rep); openReportPanel(); })
    .catch(function (e) { console.error("report fetch:", e); });
}
```

`renderReport(rep)` must:

- Handle `null` for `physiology` / `states` / `episodes` / `early_warnings` / `alerts` / `provenance` by
  rendering *"not available — {reason from rep.unavailable}"* — **never** `0`, `—`, or a hidden card.
- Show a "PROVISIONAL" stamp on each section when `reliability === "LIMITED"`.
- Show a "PARTIAL — session still running" banner when `status === "partial"`.
- Show an "INTERRUPTED — the backend restarted during this session" banner when
  `status === "interrupted"`.

Starting a new session while a report is open closes the panel; a report opened from the Sessions list
**stays valid** (it is an immutable file addressed by id), so the only change is a small banner noting a new
session is now running.

### P6 acceptance checks

1. Ending a session opens the report panel automatically with real numbers.
2. The reliability banner is the first thing visible.
3. The state timeline segment widths match `states.pct` and use the existing state colours.
4. All three downloads work; the HTML file opens correctly **with the network disabled**.
5. `GET /session/<running-id>/report` returns `status: "partial"` and `reliability: "PARTIAL"` — it does
   **not** 404 or error.
6. `GET /session/..%2f..%2fetc/report` and `GET /session/nonsense/report` both return 404.
7. `/sessions` lists prior sessions newest-first; clicking one renders its report.
8. Starting a new session with a report open transitions cleanly; the previously opened report is still
   reachable from the Sessions list.
9. An `INSUFFICIENT` report shows explanatory "not available" text for suppressed sections, not blanks.

**Commit:** `feat(report): in-app session report, downloads, sessions list (P6)`

---

## P7 — Robustness and documentation

**Goal:** Survive a backend restart, then verify and document everything.

**Files:** `backend/state_service.py`, `README.md`, `CODEBASE_MEMORY.md`.

### P7.1 Interrupted-session recovery

In `AnxietyStateService.start_reader()`, **before** starting the reader thread, scan `sessions_dir()` for
`*.partial.json`. For each:

1. Load it. If it fails to parse, rename to `<name>.corrupt` and continue — never crash on boot.
2. Set `status = "interrupted"`, `identity.end_reason = "interrupted"`.
3. Re-grade reliability from the numbers present (it will usually be `INSUFFICIENT` or `LIMITED`).
4. Append a narrative line: `"This session was interrupted; the backend stopped before it was ended normally. Figures cover only the recorded portion."`
5. Write `<id>.json` and delete the `.partial.json`.

Log one INFO line per recovered session. This must never prevent startup — wrap the whole scan in
`try/except Exception`.

### P7.2 Documentation

**README.md** — add sections at the end (do not rewrite existing ones):

- *Session lifecycle* — the four phases, the transition table, what resets on start.
- *API contract additions* — the §3.9 table.
- *Snapshot addition* — the `session` block from §3.3.
- *Session report* — the §3.4 schema, the §3.5 reliability rules, and a short
  **"what the report deliberately does not include and why"** list: HRV/RMSSD (the 1 Hz single averaged BPM
  stream has no inter-beat intervals, so HRV would be fabricated), 0–100 stress scores or percentiles (no
  validated normative population), clinical severity ratings, cross-session trend analytics.
- *CSV schema v2* — new columns and the `physio_log.pre_sessions.csv` rotation.
- *New config env vars* — `ANXIETY_CALIB_STALL_FACTOR`, `ANXIETY_SESSION_CHECKPOINT_S`,
  `ANXIETY_SESSION_AUTOSTART`.

**CODEBASE_MEMORY.md** — add the three new modules to the module table, the new routes to the API contract
section, and the new snapshot field. Also correct these now-stale entries while you are there:
"No exposed session reset route" and "Frontend doesn't display pattern, alert, features".

### P7.3 Full regression pass — Section 7 checklist

Run every item in Section 7. Fix anything that fails before declaring the work done.

**Commit:** `feat(session): interrupted-session recovery and documentation (P7)`

---

## 5. EDGE CASE MATRIX — required behavior

This is the acceptance specification for correctness. Each row must be true in the finished system.

| # | Situation | Required behavior | Phase |
|---|---|---|---|
| 1 | First session ever | `data/sessions/` created on demand; empty Sessions list shows an empty state, not an error | P1/P6 |
| 2 | Second person starts a session | `_reset_session_locked()` runs; **zero** baseline carryover; UI says a new baseline will be measured | P1 |
| 3 | Start while a session is running | `409 session_active`; **no** new id; existing session untouched | P1 |
| 4 | End "too early" | **Always allowed.** Session ends; report graded `INSUFFICIENT` with reasons | P1/P4 |
| 5 | Calibration gets too few valid readings | Stays `CALIBRATING`; `stalled: true`; coaching copy; Restart offered | P2 |
| 6 | Ended during calibration | `end_reason: "ended_during_calibration"`; `baseline.completed: false`; report has identity/quality/baseline only | P1/P4 |
| 7 | Sensor disconnects during calibration | Stays `CALIBRATING`; `paused: true`; buffer **not** wiped; resumes on reconnect | P2 |
| 8 | Sensor disconnects during monitoring | Session continues; gap recorded in `quality.disconnections`; gap time attributed to **no** state | P3 |
| 9 | Calibration restart | Same session id; `attempts += 1`; progress back to ~0 | P2 |
| 10 | Browser refresh | Fully transparent — phase, label, and elapsed time come from the snapshot. Only the 60-point chart history is lost (acceptable) | P1 |
| 11 | Backend restart mid-session | On boot the `.partial.json` is finalized as `status: "interrupted"`; ≤10 s of data lost | P7 |
| 12 | Session with very little data | One mechanism: `reliability` grade + reasons. Sections suppressed with `unavailable` entries | P4 |
| 13 | Session with no stress/anxiety events | `episode_count: 0`; narrative states this as a **valid, normal** result | P4 |
| 14 | Repeated start/end thrashing | Idempotent endpoints; short sessions still saved, flagged `INSUFFICIENT` | P1/P4 |
| 15 | Intervention then session end | Intervention recorded; `completion: "aborted_by_session_end"` if still running | P5 |
| 16 | Session ends in STRESS / ANXIETY / RECOVERY | `terminal_state` recorded; final episode `resolved_via: "open_at_session_end"`; **no synthesized resolution** | P4 |
| 17 | Many state transitions | Episode floor of 5 s + FSM hold timers filter flicker; high transition count cross-referenced with `unstable_signal_pct` | P4 |
| 18 | Multiple interventions | Each recorded separately with its own recovery window; aggregates in `intervention_summary` | P5 |
| 19 | No intervention | Section renders *"No breathing exercise was performed during this session"* — a stated absence, not a blank | P4/P6 |
| 20 | Session ends immediately after an intervention | `recovery_data: "truncated"`; `hr_at_plus_60s: null` + `unavailable` entry. **Do not extrapolate.** | P5 |
| 21 | Missing / invalid sensor readings | Dropped by `DataPipeline` / `compute_features` as today; counted in `samples_rejected`; lowers `coverage_pct` | P3 |
| 22 | Degraded signal quality | `mean_confidence` + `unstable_signal_pct` drive the grade down to `LIMITED` | P3/P4 |
| 23 | Report field unavailable | `null` + an `unavailable` entry; UI renders *"not available — reason"*. **Never 0, never blank, never hidden** | P4/P6 |
| 24 | Download before the session ends | Partial JSON with `status: "partial"` and `reliability: "PARTIAL"` baked into the file | P6 |
| 25 | New session while an old report is open | Non-issue by construction — ended reports are immutable files addressed by id; open report stays readable, banner notes the new session | P6 |
| 26 | Malicious / malformed session id | Regex-validated before any filesystem access; 404 otherwise | P6 |
| 27 | Corrupt `.partial.json` on boot | Renamed to `.corrupt`; startup proceeds | P7 |
| 28 | Recorder throws | Caught and logged at debug; live monitoring unaffected | P3 |

---

## 6. LANGUAGE AND CLAIMS RULES (applies to UI copy, narrative, comments, README)

### Required

- `disclaimer` (§3.4) appears in the report view **and** in the downloaded HTML, verbatim.
- Intervention results are stated **observationally**: *"HR decreased 11 bpm over the 60 s following the
  exercise."*
- Early-warning results are stated as *"N issued, M confirmed"*.
- Reliability is always shown **before** the metrics it qualifies.

### Banned anywhere in the product

- Causal claims about interventions: *reduced stress*, *treated*, *cured*, *fixed*, *improved anxiety*,
  *calmed the user down*.
- Diagnostic or clinical language: *diagnosis*, *disorder*, *patient*, *symptoms*, *clinically*,
  *medically significant*, *healthy/unhealthy*.
- Accuracy or validation claims about the forecast or the model: *accuracy*, *validated*, *proven*,
  *X% correct*.
- Absolute health judgements about the person. **Grade the data, never the human.**
- HRV, RMSSD, SDNN, or any inter-beat-interval metric — **the data cannot support it** (1 Hz single
  averaged BPM value). If asked to add it, refuse and cite this line.

---

## 7. FINAL REGRESSION CHECKLIST

Run all of these at the end of P7. Mock mode is sufficient.

### Existing functionality (must be unchanged)

- [ ] `$env:ANXIETY_USE_MOCK_SERIAL=1; python app.py` starts with no traceback
- [ ] `GET /data` contains all 19 original fields from §1.3 with unchanged types
- [ ] `GET /stream` emits one payload per second
- [ ] HR and GSR cards update, including mini-bars and trend arrows
- [ ] The state card shows CALM / STRESS / ANXIETY / RECOVERY with the correct colour class
- [ ] The 60-point live chart scrolls and the state transition markers appear
- [ ] The connection pill reflects mock / connected / no_data / disconnected
- [ ] The calibration banner appears before calibration and the compact status strip replaces it after
- [ ] The prediction strip shows countdowns when a forecast is active
- [ ] The breathing prompt appears on elevated state and the breathing modal runs a full box cycle
- [ ] The in-modal recovery summary card still renders
- [ ] The Research & Evidence drawer opens and closes
- [ ] `POST /session/exercise` still returns 200 and still writes its CSV marker
- [ ] `data/logs/physio_log.csv` is still being appended to once per second
- [ ] `python ml/train.py` still runs (ML pipeline untouched)

### New functionality

- [ ] Start / End work; the button label tracks the phase
- [ ] The session label appears in the chip and in the report
- [ ] `CALIBRATING -> MONITORING` happens automatically
- [ ] The calibration ring reflects true progress and never hangs at 100%
- [ ] `stalled` coaching appears and Restart calibration works
- [ ] `session.live` updates during monitoring
- [ ] A `.partial.json` appears during a session and is removed on a clean end
- [ ] The report opens automatically on end, with the reliability banner first
- [ ] The state timeline widths match `states.pct`
- [ ] JSON / HTML / CSV downloads all work; the HTML opens offline
- [ ] `/sessions` lists past sessions newest-first
- [ ] Browser refresh mid-session is transparent
- [ ] Killing and restarting the backend mid-session yields an `interrupted` report on next boot

### Edge cases (spot-check at minimum rows 3, 4, 10, 13, 16, 20, 23, 26)

- [ ] Section 5 matrix rows verified

### Hygiene

- [ ] `requirements.txt` unchanged
- [ ] No file in §2.2 modified (`git diff --name-only` to confirm)
- [ ] No new `<script src>` in `frontend/index.html`
- [ ] No banned language from §6 anywhere in the diff
- [ ] `git status` shows no stray debug files added at the repo root

---

## 8. OPEN DECISIONS (default chosen — change only if the owner says so)

1. **CSV rotation.** Default: rename the existing `physio_log.csv` to `physio_log.pre_sessions.csv` on
   first v2 boot. The current file already has a drifted header (F-H), so it cannot be extended in place.
   *Alternative if the owner objects: keep v1 writing untouched and write a second
   `physio_log_v2.csv` — more files, more confusion, not recommended.*
2. **`state` during IDLE.** Default: the backend leaves `state` as `"CALM"` (what a fresh reset produces)
   and the **frontend** renders `IDLE` when `session.recording !== true`. This keeps `state` non-null, which
   the frontend has always assumed. *Alternative: emit `state: null` in IDLE — more honest in the API, but
   it changes a long-standing field's nullability.*
3. **Chart rehydration after refresh.** Default: accept losing the 60-point chart history on refresh.
   *Optional later addition: a server-side 300-sample ring buffer plus a `GET /history` route. Do not build
   this unless asked.*
