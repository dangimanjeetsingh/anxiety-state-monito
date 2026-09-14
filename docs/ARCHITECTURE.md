# Architecture and internals

How the system actually works, stage by stage: the runtime pipeline from serial
byte to rendered state, the module and frontend guides, the HTTP/SSE contract,
the session lifecycle and report, and the on-disk data formats.

For what the project is and how to run it, see the [README](../README.md).
For the record of how it got here, see the [changelog](CHANGELOG.md).

---

## End-to-end runtime flow

### 1. Startup

`app.py` is the entry point. It:

1. Configures logging.
2. Loads all application configuration from `backend/config.py`.
3. Instantiates `AnxietyStateService`.
4. Starts the Bluetooth/mock reader thread.
5. Creates the Flask application.
6. Runs the dashboard server.

### 2. Data input

Incoming data reaches the system through `backend/bt_reader.py`.

The reader:

- Connects to the configured serial port.
- Reads bytes from the device.
- Buffers and splits input by newline.
- Extracts GSR and HR values using regex.
- Emits parsed samples into the backend service callback.
- Reports connection and sensor statuses separately.

Accepted line patterns are flexible. The parser supports:

- `GSR:<value>,HR:<value>`
- `BSP:<value>,BPM:<value>`
- GSR/HR appearing in any order in the line
- Integer or float values

Examples:

```text
GSR:520,HR:72
HR:72 GSR:520
BSP=520,BPM=72
```

The reader also recognizes non-numeric guidance messages such as lines containing words like `finger`, `place`, or `wait`, and surfaces them to the UI as a sensor warning.

### 3. Input validation and smoothing

Raw samples are pushed into `backend/pipeline.py`.

This stage:

- Rejects clearly invalid ranges
- Maintains a moving average over the last `N` accepted samples
- Builds a rolling time window of smoothed samples

Default range checks in the pipeline:

- HR must be between `40` and `210`
- GSR must be between `0` and `1200`

Default smoothing/window settings:

- Moving average window: `3` samples
- Sliding window duration: `30` seconds

If the moving average buffer has not filled yet, the sample is not promoted into the main feature window.

### 4. Baseline calibration

`backend/features.py` contains `BaselineTracker`, which learns the user's resting HR and GSR during an initial calibration period.

Default behavior:

- Calibration length: `30` seconds
- Requires enough stable samples before locking the baseline
- No predictions are produced until calibration completes

Important calibration rules:

- If both `ANXIETY_FIXED_BASELINE_HR` and `ANXIETY_FIXED_BASELINE_GSR` are provided, dynamic calibration is skipped and the baseline is treated as ready immediately.
- If dynamic calibration is used, the tracker keeps sliding forward until it finds a stable enough period.
- Optional drift adaptation logic exists in the tracker, but it is disabled by default.

### 5. Feature extraction

Once calibration is ready and enough data is present in the window, `compute_features()` creates a feature vector.

The feature vector fields are:

- `mean_hr`
- `std_hr`
- `hr_trend`
- `mean_gsr`
- `std_gsr`
- `gsr_trend`
- `delta_hr`
- `delta_gsr`
- `stress_index`
- `confidence`

How the main features are computed:

- Means and standard deviations come from the current rolling window
- Trends are normalized least-squares slopes over the window
- `delta_hr` and `delta_gsr` are differences from the baseline
- `stress_index` is a weighted combination of delta HR and delta GSR
- `confidence` is a quality score based on sample volume, outlier survival, and signal stability

Additional quality gates in feature extraction:

- The window must contain at least `10` samples
- The window must span at least `10` seconds
- HR outliers are clamped to `40..180`
- GSR outliers are filtered using an IQR rule
- If more than half the window is rejected as noisy, no features are returned

### 6. Rule-based classification

`backend/rules.py` contains `RulesEngine`.

It uses:

- HR/GSR deltas
- HR trend
- Previous rule state
- Confidence score

It can classify the signal as:

- `CALM`
- `STRESS`
- `ANXIETY`
- `ACTIVE`

Rule logic summary:

- High HR delta and high GSR delta suggest `ANXIETY`
- Fast HR rise without matching GSR rise suggests `ACTIVE`
- Moderate elevation suggests `STRESS`
- Falling HR trend can help transition out of elevated states
- Low confidence causes conservative downgrades to avoid false alarms

### 7. Machine learning prediction

`backend/ml_predictor.py` loads a model from `ml/model.pkl` and optionally a scaler from `ml/scaler.pkl`.

Runtime behavior:

- If the model file is missing or fails to load, ML is disabled
- If the scaler exists, it is applied before prediction
- If the model supports `predict_proba`, the top probability becomes the ML confidence

Important limitation:

- The training script maps labels only to `CALM` and `ANXIETY`
- The model therefore does not natively represent `STRESS`, `ACTIVE`, or `RECOVERY`

### 8. Rule/ML fusion

`backend/fusion.py` contains `FusionEngine`.

Fusion is intentionally conservative:

- If ML is unavailable, the rule result is used
- If ML predicts `ANXIETY` with enough effective confidence, it can override rules
- If ML predicts `CALM`, it does not override a rule-level `STRESS` or `ACTIVE`

Effective confidence is:

```text
ml_confidence * feature_confidence
```

Default ML override threshold:

- `0.75`

Fusion source values:

- `rules`
- `ml`
- `both`

### 9. State smoothing

`backend/prediction_smoother.py` reduces flicker before the FSM sees the label stream.

It performs:

- Majority voting over a recent history buffer
- Hysteresis confirmation before switching the current output state

Default settings:

- History size: `7`
- Confirm streak: `2`

### 10. Final finite state machine

`backend/state_machine.py` is the final authority on the displayed state.

Valid FSM states:

- `CALM`
- `STRESS`
- `ANXIETY`
- `RECOVERY`

Upstream `ACTIVE` is normalized into `STRESS` here.

The FSM enforces hold times so that abrupt one-sample jumps do not immediately change the final state.

Key transitions:

- `CALM -> STRESS` requires `STRESS` input for at least `3s`
- `STRESS -> ANXIETY` requires `ANXIETY` input for at least `3s`
- `STRESS -> CALM` requires `CALM` input for at least `3s`
- `ANXIETY -> RECOVERY` requires de-escalated input plus falling HR for at least `5s`
- `RECOVERY -> CALM` requires `CALM` input for at least `5s`

Special FSM rules:

- Direct `CALM -> ANXIETY` is blocked unless `stress_index > 12.0`
- Even the direct emergency path still requires a `3s` hold
- `ANXIETY -> CALM` is never direct; it must pass through `RECOVERY`

### 11. Pattern detection

`backend/pattern_detector.py` watches feature history across roughly `60` seconds to detect higher-level patterns.

Possible pattern outputs:

- `UNSTABLE_SIGNAL`
- `RAPID_STRESS_SPIKE`
- `GRADUAL_STRESS_BUILD`
- `SLOW_RECOVERY`
- `NORMAL`

Pattern meanings:

- `UNSTABLE_SIGNAL`: low confidence or very noisy feature variance
- `RAPID_STRESS_SPIKE`: quick rise in delta HR and delta GSR over the last `5-10` seconds
- `GRADUAL_STRESS_BUILD`: slower upward drift in stress index over roughly `20-40` seconds
- `SLOW_RECOVERY`: HR trend is falling, but only gradually
- `NORMAL`: no special temporal pattern detected

### 12. Alert generation

`backend/alert_system.py` converts final state and detected pattern into an alert level.

Alert outputs:

- `NONE`
- `LOW`
- `MEDIUM`
- `HIGH`

Alert rules:

- `HIGH`: sustained `ANXIETY` for more than `10s` with confidence above `0.6`
- `MEDIUM`: sustained `STRESS` for more than `20s` or a `RAPID_STRESS_SPIKE`
- `LOW`: `GRADUAL_STRESS_BUILD` or `SLOW_RECOVERY`
- `NONE`: everything else

### 13. Predictive early-warning (trend forecast)

`backend/trend_predictor.py` runs after the FSM and alert system. It projects short-horizon physiological trends using the current feature window (`hr_trend`, `gsr_trend`, `stress_index`) and rule thresholds.

Behavior:

- Only active after calibration (`calibrated === true`) and when feature confidence meets `ANXIETY_PREDICT_MIN_CONFIDENCE` (default `0.5`).
- From `CALM`, forecasts escalation toward `STRESS`; from `STRESS`/`RECOVERY`, forecasts toward `ANXIETY`.
- Uses the **final FSM state** for both the displayed target (`CALM` → forecast `STRESS`, etc.) and for knowing when a forecast has landed.
- Uses the **pre-FSM smoothed label** only to suppress the banner when ML/fusion is already at `ANXIETY` (the breathing prompt handles that case instead).
- Keeps warnings visible while the FSM is still holding, even if `stress_index` has already crossed a rule threshold.
- Clears on trend reversal (two consecutive falling HR-trend samples) or when the horizon exceeds `ANXIETY_PREDICT_MAX_HORIZON_S` (default `30s`).

The UI reads the `prediction` object from `/stream` and renders the amber `#predictionBanner`.

### 14. Snapshot, logging, and serving

`backend/state_service.py` coordinates the entire pipeline and stores the latest application snapshot behind a thread lock.

It also:

- Starts and stops the background reader
- Opens the CSV log
- Updates connection status
- Logs raw and processed readings
- Exposes current state as a JSON-ready dictionary

The default CSV log file is:

```text
data/logs/physio_log.csv
```

CSV columns:

- `timestamp_iso`
- `hr`
- `gsr`
- `raw_line`
- `rule_state`
- `ml_state`
- `fused_state`
- `final_state`
- `connection`

Important logging detail:

- During warmup or calibration, some processed columns can be blank because the system logs incoming data even before full feature extraction and classification are available.

## Backend module guide

| File | Responsibility |
| --- | --- |
| `app.py` | Entry point that boots logging, config, state service, and Flask |
| `backend/config.py` | Central application configuration and environment variable mapping |
| `backend/paths.py` | Path helpers for repo root, data, logs, and ML artifacts |
| `backend/bt_reader.py` | Bluetooth/serial or mock data ingestion |
| `backend/pipeline.py` | Range checks, moving average smoothing, and sliding window storage |
| `backend/features.py` | Baseline tracking, feature engineering, and confidence scoring |
| `backend/rules.py` | Rule-based physiological state classification |
| `backend/ml_predictor.py` | ML model loading and inference |
| `backend/fusion.py` | Controlled rule/ML fusion |
| `backend/prediction_smoother.py` | Majority-vote smoothing and hysteresis |
| `backend/state_machine.py` | Final transition-constrained state machine |
| `backend/pattern_detector.py` | Temporal pattern analysis across feature history |
| `backend/alert_system.py` | Alert-level generation based on state and pattern |
| `backend/trend_predictor.py` | Short-horizon trend forecast for early-warning UI banner |
| `backend/state_service.py` | Main orchestrator, logging layer, and JSON snapshot provider |
| `backend/flask_app.py` | Web routes, CORS, SSE, and static frontend serving |

## Frontend guide

The frontend is a static dashboard served directly by Flask from the `frontend/` directory.

### Files

| File | Responsibility |
| --- | --- |
| `frontend/index.html` | Layout, cards, chart canvas, status bar, status strip, and device instructions |
| `frontend/js/app.js` | SSE subscription, DOM updates, chart updates (incl. state-transition markers), and connection UI logic |
| `frontend/css/style.css` | Design tokens (`:root`), dashboard styling, state colors/animations, status indicators, and instructions panel |

### Design system (UI redesign, phases 1-10 — see the [changelog](CHANGELOG.md))

The frontend went through a 10-phase visual redesign after the original build. The result:

- **Design tokens** live in `style.css`'s `:root`: `--bg-base`, `--bg-panel`, `--ink`, `--calm`, `--stress`, `--anxiety`, `--recovery` (plus supporting tokens — `--bg-elevated`, `--border`, `--muted`, `--accent`, and RGB-triplet companions for alpha-blended backgrounds). `--active` is aliased to `--stress` since the legacy `ACTIVE` FSM class is unreachable in the final state machine. Every color in the stylesheet is token-driven; nothing is hardcoded.
- **Typography**: `Sora` for headings/body/labels, `JetBrains Mono` for numeric readouts (HR/GSR values, timers, countdowns, decision-table thresholds), both loaded via Google Fonts `@import`.
- **Layout**: `.cards` is a CSS Grid — the state card at `2fr` beside a `.side-cards` column (`1fr`) holding Heart Rate and GSR stacked, with the chart full-width below. Collapses to a single column (state → HR → GSR → chart) below 768px.
- **State card**: a circular `.state-ring` (SVG pulse icon + state name), a divider, and state-specific micro-copy (CALM/STRESS/ANXIETY/RECOVERY), shown/hidden via the same `state-card.state-*` classes `app.js` already toggles. A single continuous pulse animation (glow, HR-linked rate) plus a ~350-400ms color crossfade on state change; both disabled under `prefers-reduced-motion: reduce`.
- **HR/GSR cards**: heart/droplet SVG icons, a decorative 7-bar sparkline, and static reference range text ("Normal range · 60–100 bpm", "Typical range · 100–1000 µS") — not wired to live data.
- **Status strip** (`#statusStrip`): replaces the full-width calibration banner once `calibrated === true` with a compact "✓ Calibrated" pill (click-to-expand baseline detail) plus the prediction pill re-skinned in place — falls back to a neutral "Next reading in ~1s" message when no prediction is active, rather than leaving an empty gap.
- **Chart**: `chartjs-plugin-annotation` draws a dashed line + colored label pill at each FSM state transition, pruned to stay within the rolling 60-point window.
- **Breathing button**: a floating circular button (bottom-right) replacing the old full-width button; the modal backdrop is softened (dashboard stays legible behind it) and its palette is teal/indigo-led (no amber/coral except the Stop button).
- **Header**: heartbeat/pulse icon + "Real-time monitoring for a healthier you." subtitle; no tracked-out uppercase chrome. The old HC-05/fusion meta line now opens the evidence drawer instead.

### What the frontend displays

- Current HR / GSR (with decorative range indicators)
- Current physiological state (state ring + state-specific micro-copy)
- Rule state / ML state / fusion source text
- Connection state bar
- Calibration banner during calibration, replaced by the compact status strip once calibrated
- Method & Evidence slide-out drawer ("⌁ Method & evidence" toggle)
- State interpretation table & baseline rationale
- Tier 2 ML Model transparency card
- Sensor warning banner
- Predictive early-warning pill, folded into the status strip (`#predictionBanner`)
- Non-intrusive breathing exercise prompt (`#breathingPrompt`)
- Floating breathing exercise launcher button (`#manualBreatheBtn`)
- Guided box-breathing modal (`#breathingModal`)
- Post-exercise recovery tracking summary card with sparkline chart (`#recoveryCard`)
- Baseline summary
- Window sample count and calibration flag
- Live chart with the latest 60 points and dashed state-transition markers

### Important UI details

- The frontend subscribes to `/stream` using Server-Sent Events (SSE)
- The chart is powered by Chart.js (+ `chartjs-plugin-annotation`) from a CDN
- HR is charted directly
- GSR is charted as `GSR ÷ 4` to keep both traces visible on one chart
- **Calibration Banner (`#calibrationBanner`)**: Provides immediate visual indication during the initial baseline calibration phase (default ~30 seconds), then hides once calibrated (replaced by the status strip):
  - **Waiting**: Displayed when disconnected or waiting for sensor contact.
  - **Preparing**: Displayed when device is connected but valid HR/GSR data has not arrived yet.
  - **Calibrating**: Active during the first 30 seconds of stable data collection, instructing the user to stay calm and still while baseline HR and GSR are measured (state predictions are deferred).
- **Status Strip (`#statusStrip`)**: Shown once `calibrated === true`. Always has a "✓ Calibrated" pill (click/tap to expand the real baseline HR/GSR) plus a second pill:
  - **Prediction active**: an amber "⚡ Trending toward `<STATE>` in ~Xs" pill with a distinct countdown badge, re-rendered directly each second from server snapshot data without timer drift. Clears upon trend reversal or once the FSM reaches the predicted state. Uses the same feature pipeline as rules/ML (not a separate data path).
  - **No prediction active**: a neutral "⏱ Next reading in ~1s" pill instead of an empty gap; its countdown badge is hidden since there's no real countdown to show.
- **Guided Breathing & Closed-Loop Recovery (`#breathingModal`, `#recoveryCard`)**:
  - Non-intrusive prompt triggered when the final FSM state is `ANXIETY`, when `alert === "HIGH"`, when confident ML output was **adopted by fusion** (`fused_state === "ANXIETY"` and `fusion_source` is `ml` or `both` — both required), or manually via the floating breathing button. If `ml_state` shows `ANXIETY` but `fusion_source` is still `rules`, only the rule/FSM path applies.
  - Guided box-breathing (4s Inhale, 4s Hold, 4s Exhale, 4s Hold) with selectable duration (1, 2, or 3 minutes).
  - Live client-side buffering of HR, GSR, and state during exercise + 60s post-exercise recovery window over the single SSE stream.
  - Post-recovery summary card reporting initial vs. recovery HR delta, state progression (e.g. `ANXIETY → RECOVERY`), and an inline Chart.js trend graph.
  - Exercise marker events (`start`, `stop`) optionally logged via `POST /session/exercise` to `physio_log.csv`.
- **Method & Evidence Drawer (`#interpretationDrawer`)**: A slide-out transparent decision guide accessed via the "Method & evidence" button, opening with the HC-05/fusion-method meta line:
  - **State Decision Table**: Detailed breakdown showing decision rules, empirical rationale, and safeguards for each state:
    - *Calibrating*: ~30s within-person comparison setup; safeguards against premature predictions.
    - *Calm*: No persistent elevation from baseline; requires sustained readings.
    - *Stress*: Triggered by `HR > baseline + 6 bpm` or `GSR > baseline + 40`; requires smoothed, sustained input.
    - *Anxiety*: Triggered by `HR > baseline + 12 bpm` AND `GSR > baseline + 80` (or high-confidence ML override); protected by dual-signal & confidence checks.
    - *Recovery*: Triggered by falling HR trend post-anxiety; must hold for 5 seconds.
  - **Trust & Rationale**: 5-step pipeline overview (Personal baseline -> Cleaner readings -> Two-signal check -> Confirmation gate -> Early trend warning).
  - **ML Model Transparency Card**: Details the Random Forest model architecture (100 trees, depth 5), 10 input features, binary output (`CALM`/`ANXIETY`), and safety override gate (`confidence >= 0.75`).
- The UI still contains an `ACTIVE` visual class, but the final FSM state normally emits `CALM`, `STRESS`, `ANXIETY`, or `RECOVERY`
- If the stream fails, the UI shows a connection warning and retries after `3s`

### How ML, rules, and new features interact

All runtime modes (hardware serial and mock) share the **same** backend pipeline in `state_service.py`. The reader mode only changes where samples originate (`bt_reader.py`).

| UI feature | Primary JSON fields | ML-aware? |
| --- | --- | --- |
| State card | `state` (final FSM) | Yes — FSM input comes from fusion, which can ML-override to `ANXIETY` |
| Meta line | `rule_state`, `ml_state`, `fusion_source` | Displays all three explicitly |
| Early-warning banner | `prediction` | Yes — uses pre-FSM smoothed state, which only reflects ML when fusion adopted it (same confidence gate). Low-confidence ML never suppresses the banner early. |
| Breathing prompt | `state`, `alert`, `fused_state`, `fusion_source` | Yes — ML triggers breathing **only** when fusion adopted it (`fused_state === "ANXIETY"` **and** `fusion_source` is `ml` or `both`). Raw `ml_state` with `fusion_source: "rules"` is ignored. |
| Recovery summary | `state`, `hr`, `gsr` during exercise | Uses final FSM `state` timeline over SSE |
| Alerts (internal) | `alert` | Derived from final FSM state + patterns; `HIGH` also triggers breathing |

ML fusion rules (`fusion.py`):

- ML only overrides when it predicts `ANXIETY` with effective confidence ≥ `ANXIETY_ML_CONFIDENCE` (default `0.75`).
- ML `CALM` never overrides rule-level `STRESS`/`ACTIVE`.
- When ML is unavailable, everything falls back to rules-only — prediction and breathing still work.

### Data returned by the backend but not currently rendered in the dashboard

- `features` (full feature vector object)
- `pattern` (temporal pattern label)
- `fused_state` (pre-FSM fused label — shown indirectly via meta line and used internally)

Note: `alert` and `prediction` **are** used by the frontend (breathing prompt and early-warning banner). They are also available via `/data` for programmatic access.

## API contract

### `GET /`

Serves the static frontend dashboard.

### `GET /data`

Returns the latest snapshot as JSON and disables caching via headers.

### `GET /stream`

Returns an SSE stream. The server emits one JSON payload per second.

### `POST /session/exercise`

Records breathing exercise events (`start` or `stop`) as marker rows in `physio_log.csv` without mutating existing telemetry structures.
Body: `{"event": "start"|"stop", "timestamp": <unix_ts>}`.

### Snapshot schema

Top-level fields returned by `AnxietyStateService.to_json_dict()`:

| Field | Type | Meaning |
| --- | --- | --- |
| `server_time` | float | Current server timestamp |
| `hr` | float or null | Current heart rate value |
| `gsr` | float or null | Current GSR value |
| `state` | string | Final FSM state |
| `rule_state` | string | Rule engine result |
| `ml_state` | string or null | ML model output |
| `fused_state` | string | Pre-FSM fused label (after rule/ML fusion, before hold timers) |
| `fusion_source` | string | Whether rules, ML, or both determined the fused result |
| `connection` | string | Reader connection state |
| `connection_detail` | string or null | Extra detail such as COM port or disconnect text |
| `sensor_warning` | string or null | User-facing hardware warning |
| `baseline_hr` | float or null | Learned or fixed HR baseline |
| `baseline_gsr` | float or null | Learned or fixed GSR baseline |
| `features` | object or null | Engineered feature values |
| `window_samples` | integer | Number of points in the rolling window |
| `calibrated` | boolean | Whether baseline calibration has completed |
| `pattern` | string or null | Temporal pattern label |
| `alert` | string or null | Alert level |
| `prediction` | object | Early-warning prediction object with `active`, `predicted_state`, `seconds_to_transition`, `basis` |

### Example JSON payload

```json
{
  "server_time": 1760000000.0,
  "hr": 73.4,
  "gsr": 512.7,
  "state": "STRESS",
  "rule_state": "STRESS",
  "ml_state": "ANXIETY",
  "fused_state": "STRESS",
  "fusion_source": "rules",
  "connection": "connected",
  "connection_detail": "COM6",
  "sensor_warning": null,
  "baseline_hr": 69.8,
  "baseline_gsr": 488.2,
  "features": {
    "mean_hr": 73.4,
    "std_hr": 2.1,
    "hr_trend": 0.012,
    "mean_gsr": 512.7,
    "std_gsr": 18.3,
    "gsr_trend": 0.006,
    "delta_hr": 3.6,
    "delta_gsr": 24.5,
    "stress_index": 4.825,
    "confidence": 0.82
  },
  "window_samples": 28,
  "calibrated": true,
  "pattern": "GRADUAL_STRESS_BUILD",
  "alert": "LOW",
  "prediction": {
    "active": true,
    "predicted_state": "STRESS",
    "seconds_to_transition": 14.2,
    "basis": "rising stress_index trend"
  }
}
```

## API contract additions

All additive. `GET /`, `GET /data`, `GET /stream` and `POST /session/exercise` are unchanged.

| Method | Path | Body | Success | Failure |
|---|---|---|---|---|
| POST | `/session/start` | `{"label": "Visitor 12"}` (optional) | `201 {session_id, phase, label}` | `409 {error:"session_active", session_id}` |
| POST | `/session/end` | none | `200 {session_id, report_url, reliability}` | `409 {error:"no_active_session"}` |
| POST | `/session/calibration/restart` | none | `200 {session_id, attempts}` | `409 {error:"not_calibrating"}` |
| POST | `/session/intervention` | `{event, technique?, planned_duration_s?, cycles_completed?}` | `200 {status:"ok", index}` | `400 {error:"invalid_event"}` / `409 {error:"no_active_session"}` |
| GET | `/sessions` | — | `200 [...]` newest first, capped at 50 | — |
| GET | `/session/<id>/report` | — | `200 <report JSON>` | `404 {error:"not_found"}` |
| GET | `/session/<id>/report.html` | — | `200 text/html` attachment | `404` |
| GET | `/session/<id>/report.csv` | — | `200 text/csv` attachment | `404` |
| POST | `/session/exercise` | `{event}` | `200` — back-compat alias, forwards to the intervention handler | — |

Notes:

- Requesting the report of the **currently running** session returns the live partial with
  `status: "partial"` and `quality.reliability: "PARTIAL"`. It does not 404.
- Session ids are validated against `^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$` **before** any filesystem access, so
  a crafted id cannot escape `data/sessions/`.
- `event` on `/session/intervention` must be `"start"` or `"stop"`. Both are idempotent: a second start
  returns the running index and a stop with nothing running is a no-op.

## Snapshot addition: `session`

One new top-level key. Every pre-existing field keeps its name, type and meaning.

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
    "method": "personalized", "progress": 1.0, "elapsed_s": 33.0, "target_s": 30.0,
    "stable": true, "stalled": false, "paused": false, "attempts": 1
  },
  "live": {
    "reliability": "GOOD", "coverage_pct": 97.2, "episodes": 1, "warnings": 2,
    "interventions": 1, "peak_alert": "MEDIUM", "intervention_active": false
  }
}
```

In `IDLE`, `id` / `label` / `started_at` / `calibration` / `live` are `null` and `recording` / `evaluating`
are `false`. In `ENDED`, the identity fields describe the just-ended session and `live` carries its final
numbers.

## Session lifecycle

Monitoring is organised into **sessions**, one per person. The phase is owned by the backend and published
in the snapshot, so the browser is a pure renderer: refreshing the page mid-session restores the correct
phase, label and elapsed time with no client-side state.

| Phase | Meaning |
|---|---|
| `IDLE` | No session. The reader still runs and raw HR/GSR are shown, so the dashboard works as a sensor check. No evaluation, no recording. |
| `CALIBRATING` | Session active and recording. The personal baseline is being measured; `compute_features()` returns `None`, so no predictions are made. |
| `MONITORING` | Session active and recording. Full evaluation, prediction and alerting. |
| `ENDED` | Session finished and its report is available. No evaluation, no recording. |

Legal transitions:

```
IDLE        -> CALIBRATING     POST /session/start
CALIBRATING -> MONITORING      automatic, when the baseline locks
CALIBRATING -> ENDED           POST /session/end   (end_reason "ended_during_calibration")
CALIBRATING -> CALIBRATING     POST /session/calibration/restart  (same id, attempts += 1)
MONITORING  -> ENDED           POST /session/end   (end_reason "user_ended")
ENDED       -> CALIBRATING     POST /session/start (new id)
IDLE        -> IDLE            POST /session/end   -> 409 no_active_session
```

`recording` is true in `CALIBRATING` and `MONITORING`; `evaluating` is true only in `MONITORING`.

**What resets when a session starts.** `start_session()` runs the same reset the service has always had:
the data pipeline, the baseline tracker, the prediction smoother, the state machine, the pattern detector,
the alert system and the trend predictor are all re-instantiated or cleared, and the displayed baseline is
blanked. **Nothing carries over from the previous person.** Session ids are `YYYYmmdd-HHMMSS-xxxx` (local
time plus four hex characters), which is safe as a Windows filename.

### Calibration coaching

The baseline only locks once a window of samples is both long enough and stable enough. If the wearer
fidgets, that can take considerably longer than the configured window, so calibration reports its own
telemetry in `session.calibration`:

- `progress` is the true baseline-buffer span over the target, so the ring cannot sit at 100% while still
  calibrating.
- `paused` is true when the sensor link is down — nothing measured so far is lost.
- `stalled` is true once elapsed time exceeds `target * ANXIETY_CALIB_STALL_FACTOR`, which surfaces
  "hold still" coaching and a **Restart calibration** button. Restarting keeps the same session id and
  increments `attempts`.

## Session report

Ending a session writes an immutable `data/sessions/<id>.json` and opens the report in the dashboard. The
JSON is the single source of truth: the in-app panel, the HTML download and the narrative are all
projections of it.

Top-level sections: `identity`, `quality`, `baseline`, `physiology`, `states`, `episodes`,
`early_warnings`, `alerts`, `interventions`, `intervention_summary`, `provenance`, `narrative`,
`unavailable`, `disclaimer`.

**Any value that cannot be computed is `null` and gets an entry in `unavailable` explaining why. Zero is
never substituted for unknown.** The UI renders those as *"not available — {reason}"*.

### Reliability grading

Reliability is graded once and shown **before** the metrics it qualifies. The first matching tier wins, and
every reason that applies is listed.

| Grade | Condition |
|---|---|
| `INSUFFICIENT` | the baseline never completed, **or** monitored time < 60 s, **or** coverage < 40% |
| `LIMITED` | monitored time < 3 min, **or** coverage < 70%, **or** mean confidence < 0.45 |
| `GOOD` | none of the above |
| `PARTIAL` | forced while the session is still running — not graded |

An `INSUFFICIENT` report keeps `identity`, `quality` and `baseline` and nulls `physiology`, `states`,
`early_warnings`, `alerts` and `provenance`, each with an `unavailable` reason. Interventions are still
listed, because they are factual events. A `LIMITED` report is complete but every section is stamped
*provisional*.

### Episodes, warnings and interventions

- An **episode** is a run of `STRESS` or `ANXIETY` in the state machine lasting at least 5 s. `STRESS ->
  ANXIETY` is an escalation: the STRESS run closes with no resolution and is tagged `escalated`. A run
  still open when the session ends is closed as `open_at_session_end` — a resolution is never synthesized.
- **Early warnings** are reported as *"N issued, M confirmed"*. A forecast counts as confirmed when the
  predicted state actually arrives within its own horizon plus a 10 s grace. This is a count of what
  happened, not an accuracy or validation figure.
- **Interventions** (breathing exercises) are recorded by the backend, so a page refresh mid-exercise no
  longer destroys the record. Each has a 60 s observation window afterwards; if the session ends before it
  completes, `recovery_data` is `truncated` or `unavailable` and `hr_at_plus_60s` stays `null`. Results are
  stated observationally — *"HR decreased 11 bpm across the exercise"* — never causally.

### What the report deliberately does not include, and why

- **HRV / RMSSD / SDNN or any inter-beat-interval metric.** The device streams a single averaged BPM value
  at 1 Hz. There are no inter-beat intervals in that data, so any HRV figure would be fabricated.
- **A 0–100 "stress score" or percentile.** There is no validated normative population to rank a reading
  against, so a score would imply a comparison that does not exist.
- **Clinical severity ratings or anything diagnostic.** This is a wellbeing-monitoring prototype, not a
  medical device.
- **Cross-session trend analytics.** Each session measures its own fresh baseline, so numbers from
  different sessions are not comparable on a common scale.

Every report carries this line verbatim:

> Saarthi is a physiological stress and anxiety state estimation prototype for wellbeing monitoring. It is
> not a medical device and does not diagnose, treat, or provide clinical advice.

### Interrupted sessions

Checkpoints are written to `data/sessions/<id>.partial.json` every 10 s and deleted on a clean end. If the
backend stops mid-session, the next boot promotes the leftover checkpoint to a real report with
`status: "interrupted"`, re-grades it from the data present, and appends a narrative line saying so — at
most 10 s of data is lost. A checkpoint that cannot be parsed is renamed to `.corrupt` and startup
continues.

## CSV schema v2

`data/logs/physio_log.csv` gained two columns, in this order:

```
timestamp_iso, session_id, session_phase, hr, gsr, raw_line,
rule_state, ml_state, fused_state, final_state, connection, exercise_event
```

Rows written outside a recording phase carry an empty `session_id` and the current phase, so the raw trace
is never interrupted — logging continues even with no session running.

**Rotation.** An existing log whose header does not match the v2 header is renamed to
`data/logs/physio_log.pre_sessions.csv` on the first v2 boot and a fresh file is started. Appending columns
in place was not an option: the previous file already had a drifted header, so every earlier row would have
been silently misaligned.

## Inputs and outputs

### Runtime inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Serial lines | HC-05 / Bluetooth device | Live HR and GSR measurements |
| Mock samples | Internal generator | Hardware-free development and demos |
| Environment variables | Host OS | Runtime configuration |
| `ml/model.pkl` | Local file | ML inference model |
| `ml/scaler.pkl` | Local file | Optional preprocessing artifact |

### Training inputs

| Input | Source | Purpose |
| --- | --- | --- |
| `ml/data/training_data.csv` | Local dataset | Source training data for `train.py` |

The training CSV currently has:

- `5352` rows
- Label `0`: `3456` rows
- Label `1`: `1896` rows

The training script expects columns that normalize to:

- `hr`
- `gsr`
- `label`

The file currently uses headers:

```text
GSR,HR,Label
```

`train.py` lowercases headers when loading, so this works.

### Outputs

| Output | Location | Purpose |
| --- | --- | --- |
| Live dashboard | Browser via Flask | Main user-facing interface |
| JSON state snapshot | `/data` | Programmatic inspection |
| SSE stream | `/stream` | Near-real-time frontend updates |
| CSV log | `data/logs/physio_log.csv` | Session logging |
| Trained model | `ml/model.pkl` | Saved ML artifact from training |

## Machine learning pipeline

`ml/train.py` trains the binary ML model used at runtime.

### What `train.py` does

1. Loads raw HR/GSR/label rows from `ml/data/training_data.csv`.
2. Builds a real `DataPipeline` and `BaselineTracker`, matching production code.
3. Simulates chronological time progression at `1 Hz`.
4. Pushes raw data through the same smoothing/window logic used in production.
5. Computes production feature vectors.
6. Splits features into train/test sets using an 80/20 split.
7. Trains a `RandomForestClassifier`.
8. Saves the trained model to `ml/model.pkl`.

### Training label mapping

The script maps:

- `0 -> CALM`
- `1 -> ANXIETY`

This is why the model is binary, even though the runtime rules and FSM are multi-state.

### Model configuration in `train.py`

The training script currently uses:

- `n_estimators=100`
- `max_depth=5`
- `min_samples_split=10`
- `min_samples_leaf=5`
- `class_weight="balanced"`
- `random_state=42`

### Training-time baseline

Unlike live runtime calibration, `train.py` uses a fixed baseline:

- HR baseline: `75`
- GSR baseline: `500`

This makes the training pipeline deterministic and avoids a long simulated warmup period.

### Note about `scaler.pkl`

The runtime code will load `ml/scaler.pkl` if it exists, but the current training script only writes `ml/model.pkl`.

That means:

- `scaler.pkl` is optional at runtime
- the existing `scaler.pkl` in the repo appears to be a previously generated artifact, not something regenerated by the current training script

## Connection and status behavior

Connection-related states seen in the backend include:

- `starting`
- `connecting`
- `connected`
- `mock`
- `no_data`
- `disconnected`
- `error`

Sensor-specific warnings are separate from connection state and appear through `sensor_warning`.

Examples:

- device connected but user not touching sensor properly
- serial connection alive but no valid data arriving
- pyserial missing while trying to use hardware mode

## Important implementation notes

### Thread safety

The reader thread and Flask request handlers share state through `AnxietyStateService`, which protects updates with a `threading.Lock`.

### Path handling

`backend/paths.py` resolves all important directories relative to the repository root. No hardcoded absolute filesystem paths are required.

### CORS

Flask CORS is enabled, so frontend clients on other origins can call the API if needed.

### No database

The project does not use a database. State is held in memory and logs are written to CSV.

### Session reset

`AnxietyStateService.reset_session()` is the session-boundary primitive: it clears the pipeline, baseline,
smoother, state machine, pattern detector, alert system and trend predictor. `start_session()` reuses it,
so session control is exposed over HTTP through `POST /session/start` and `POST /session/end` (see
*Session lifecycle* in this document).
