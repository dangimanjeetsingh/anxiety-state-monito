# Anxiety State Monitor

A Python-based real-time physiological monitoring application that reads heart rate (HR) and galvanic skin response (GSR) data from an HC-05 Bluetooth serial connection, processes the signal through a multi-stage backend pipeline, and serves a live Flask dashboard.

This project combines:

- Real-time sensor ingestion
- Signal cleaning and smoothing
- Baseline calibration
- Rule-based state detection
- Machine learning-based anxiety detection
- Rule/ML fusion
- State smoothing and finite-state transition control
- Temporal pattern detection
- Alert generation
- A live browser dashboard with streaming updates

## What the project does

At a high level, the application tries to infer a user's physiological state from HR and GSR readings.

It supports two runtime modes:

1. Real hardware mode using a Bluetooth serial device such as an HC-05.
2. Mock mode that generates synthetic HR/GSR data for local testing without hardware.

The system estimates whether the user is in one of several states and then exposes the result to a web dashboard.

Important detail:

- The rule engine can emit `CALM`, `STRESS`, `ANXIETY`, or `ACTIVE`.
- The ML model is binary and only predicts `CALM` or `ANXIETY`.
- The final finite state machine (FSM) outputs `CALM`, `STRESS`, `ANXIETY`, or `RECOVERY`.
- `ACTIVE` exists upstream as a rule-level concept, but it is normalized to `STRESS` before the final FSM.

## Architecture at a glance

```text
Sensor or mock generator
    -> BluetoothReader
    -> DataPipeline
    -> BaselineTracker
    -> compute_features()
    -> RulesEngine
    -> MlPredictor
    -> FusionEngine
    -> PredictionSmoother
    -> StateMachine
    -> PatternDetector
    -> AlertSystem
    -> TrendPredictor (early-warning forecast)
    -> AnxietyStateService snapshot
    -> Flask API (/data, /stream)
    -> Frontend dashboard
```

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

## Repository structure

```text
project-code/
+-- app.py
+-- backend/
|   +-- __init__.py
|   +-- alert_system.py
|   +-- bt_reader.py
|   +-- config.py
|   +-- features.py
|   +-- flask_app.py
|   +-- fusion.py
|   +-- ml_predictor.py
|   +-- paths.py
|   +-- pattern_detector.py
|   +-- pipeline.py
|   +-- prediction_smoother.py
|   +-- rules.py
|   +-- state_machine.py
|   +-- trend_predictor.py
|   `-- state_service.py
+-- data/
|   `-- logs/
|       `-- physio_log.csv
+-- frontend/
|   +-- css/
|   |   `-- style.css
|   +-- js/
|   |   `-- app.js
|   `-- index.html
+-- ml/
|   +-- data/
|   |   `-- training_data.csv
|   +-- model.pkl
|   +-- scaler.pkl
|   `-- train.py
+-- requirements.txt
`-- various debug and diagnostic artifacts
```

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

### Design system (UI redesign, phases 1-10 — see "UI Redesign Progress Log" below)

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

## Configuration

All core configuration is centralized in `backend/config.py`.

### Serial and hardware settings

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANXIETY_COM_PORT` | `COM6` | Serial port used for HC-05 |
| `ANXIETY_BAUD` | `9600` | Serial baud rate |
| `ANXIETY_SERIAL_TIMEOUT` | `1.0` | Read timeout in seconds |
| `ANXIETY_RECONNECT_DELAY` | `2.0` | Delay before reconnect attempts |
| `ANXIETY_USE_MOCK_SERIAL` | `False` | Enable synthetic data mode |

### Baseline and stress settings

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANXIETY_BASELINE_CALIBRATION_S` | `30.0` | Baseline calibration window |
| `ANXIETY_FIXED_BASELINE_HR` | unset | Fixed HR baseline |
| `ANXIETY_FIXED_BASELINE_GSR` | unset | Fixed GSR baseline |
| `ANXIETY_STRESS_W_HR` | `1.0` | HR weight in stress index |
| `ANXIETY_STRESS_W_GSR` | `0.05` | GSR weight in stress index |

### Rule thresholds

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANXIETY_THR_DELTA_HR` | `12.0` | HR delta threshold for anxiety |
| `ANXIETY_THR_DELTA_GSR` | `80.0` | GSR delta threshold for anxiety |
| `ANXIETY_THR_STRESS_HR` | `6.0` | HR delta threshold for stress |
| `ANXIETY_THR_STRESS_GSR` | `40.0` | GSR delta threshold for stress |
| `ANXIETY_THR_ACTIVITY_HR_TREND` | `0.005` | HR trend threshold for activity |
| `ANXIETY_THR_ACTIVITY_GSR_DELTA` | `25.0` | Maximum GSR delta for activity |
| `ANXIETY_THR_RECOVERY_HR_TREND` | `-0.003` | HR trend threshold for recovery |

### Pipeline and smoothing

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANXIETY_MA_WINDOW` | `3` | Moving average length |
| `ANXIETY_WINDOW_S` | `30.0` | Sliding window duration |
| `ANXIETY_PRED_HISTORY` | `7` | Smoother history size |
| `ANXIETY_HYSTERESIS_CONFIRM` | `2` | Smoother confirmation count |

### ML and logging

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANXIETY_ML_CONFIDENCE` | `0.75` | Minimum effective confidence for ML override |
| `ANXIETY_CSV_LOG_INTERVAL` | `1.0` | CSV logging interval in seconds |
| `ANXIETY_LOG_LEVEL` | `INFO` | Logging verbosity |

### Predictive early-warning settings

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANXIETY_PREDICT_MIN_CONFIDENCE` | `0.5` | Minimum feature confidence to emit trend forecasts |
| `ANXIETY_PREDICT_MAX_HORIZON_S` | `30.0` | Maximum forecast horizon in seconds (extrapolation cap) |

### Server settings

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ANXIETY_HOST` | `127.0.0.1` | Flask bind host |
| `ANXIETY_PORT` | `5000` | Flask bind port |

## How to run the project

### Prerequisites

- Python environment with the packages from `requirements.txt`
- Optional HC-05 serial device sending HR/GSR lines
- A browser for the dashboard

### Install dependencies

Use your environment's Python launcher to install requirements:

```bash
pip install -r requirements.txt
```

### Run in hardware mode

Set the serial port if needed, then start the app:

```powershell
$env:ANXIETY_COM_PORT="COM6"
python app.py
```

The dashboard will be available at:

```text
http://127.0.0.1:5000/
```

### Run in mock mode

```powershell
$env:ANXIETY_USE_MOCK_SERIAL="1"
python app.py
```

Mock mode uses the **same pipeline as hardware**. `BluetoothReader` emits synthetic lines at 1 Hz through the identical parse → pipeline → classify path.

Mock sequence:

1. **Calibration warmup** (default 30 s): calm, low-noise HR/GSR so baseline calibration can finish reliably (matches `ANXIETY_BASELINE_CALIBRATION_S`).
2. **Repeating 30 s cycle** after calibration:
   - calm period (~10 s)
   - stress build (~5 s)
   - anxiety peak (~5 s)
   - recovery (~10 s)
   - random noise and occasional spikes

Expect the early-warning banner ~10–15 s after the post-calibration stress ramp begins (roughly 40–45 s from session start). Hardware timing depends on real physiology instead of the scripted cycle.

### Retraining the model

```powershell
python ml/train.py
```

## Device usage workflow

The dashboard itself already contains user instructions, but the intended flow is:

1. Wear the sensor with stable skin contact.
2. Power on the device.
3. Wait for Bluetooth connection.
4. Stay still during the baseline calibration period.
5. Keep the hand still during the whole session.

This last point matters because the codebase and UI both assume there is no accelerometer-based motion compensation.

In practice:

- movement can create HR spikes
- those spikes can distort features
- distorted features can trigger false `STRESS` or `ANXIETY` classifications

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

### No exposed session reset route

`AnxietyStateService` has a `reset_session()` method, but the current Flask app does not expose an HTTP endpoint for it.

## Auxiliary files in the repository

Besides the main source code, the repository currently includes a number of development artifacts such as:

- `backend_test.txt`
- `bg_test.txt`
- `clean_json.txt`
- `clean_test.txt`
- `diag2.txt`
- `diag_out.txt`
- `json_test.txt`
- `tmp_debug.py`
- `tmp_fsm_results.txt`
- `train_log.txt`
- `train_log2.txt`
- `train_log3.txt`
- `train_log4.txt`
- tracked `__pycache__` directories

These are not part of the main runtime architecture. They look like ad hoc debug outputs, diagnostics, or temporary development helpers rather than a formal automated test suite.

## Known limitations and caveats

1. The ML model is binary (`CALM` vs `ANXIETY`), while the live system uses richer rule and FSM states.
2. The frontend does not yet visualize `pattern`, `alert`, or raw feature values even though the backend exposes them.
3. Motion artifacts are a real risk because the current setup does not model accelerometer-based movement correction.
4. The dashboard depends on Chart.js from a CDN, so a fully offline frontend setup would need a local copy.
5. The repository currently contains generated artifacts and cache files that would usually be excluded from source control.
6. There is no formal unit test or integration test suite checked into the repo.

## Summary

This repository is structured as a real-time physiological monitoring stack with a clear separation between:

- ingestion (`bt_reader.py`)
- signal processing (`pipeline.py`, `features.py`)
- decision logic (`rules.py`, `ml_predictor.py`, `fusion.py`)
- stabilization (`prediction_smoother.py`, `state_machine.py`)
- higher-level interpretation (`pattern_detector.py`, `alert_system.py`)
- presentation (`flask_app.py`, `frontend/`)

The core design is sensible for a prototype or academic project:

- it can run with or without hardware
- it learns a personal baseline before predicting
- it combines deterministic rules with ML
- it uses an FSM to avoid unrealistic instant state flips
- it already exposes richer telemetry than the UI currently displays

If you need to explain the project quickly, the simplest description is:

```text
This is a real-time anxiety-state monitoring dashboard that ingests HR and GSR data, calibrates a personal baseline, extracts physiological features, combines rule-based and ML inference, stabilizes the result with smoothing and a finite state machine, and streams the final state to a live Flask frontend.
```

## UI Regression Checklist

Re-run in mock mode (`ANXIETY_USE_MOCK_SERIAL=1`, `python app.py`) after every UI redesign phase.

- [x] Calibration → normal display works (banner transitions from calibrating to prediction-active; state card shows live FSM state after ~30s)
- [x] SSE updates every second with no browser console errors
- [x] Prediction banner appears when `prediction.active` is true and disappears when it clears
- [x] Full breathing exercise flow: prompt or manual button → modal → duration select → phases → stop → recovery countdown → summary card
- [x] Evidence drawer (`Method & evidence`) opens and closes
- [x] "How to use the device" expands and collapses
- [x] No horizontal scrollbar at desktop (~1280px) and ~1024px widths (added in Phase 1+)

**Phase 0 baseline (2026-09-11):** git tag `ui-redesign-phase-0-baseline` on commit `af1a187`. All checklist items above verified passing in mock mode except the horizontal-scroll item (not yet in scope).

## UI Redesign Progress Log

- **Phase 0** — `README.md` — Baseline snapshot (`ui-redesign-phase-0-baseline` tag) and regression checklist added; mock-mode API + browser verification passed — no deviations
- **Phase 1** — `frontend/css/style.css` — Removed the pre-existing `overflow-x: hidden` stopgap on `body`; root-caused all four typical overflow sources from the spec (fixed-width canvas, hardcoded px widths, missing `box-sizing`, missing viewport meta) and found none present — Chart.js already used `maintainAspectRatio: false`, `box-sizing: border-box` was already global, and the viewport meta tag already existed. Verified zero horizontal overflow at 320/375/768/1024/1280/1440px, with the evidence drawer open and through the full breathing-modal flow, before and after removing the stopgap. Deviation: no root-cause fix was needed since the bug wasn't reproducible in current code — treated the stopgap removal itself as the fix per the spec's "don't use overflow-x:hidden as more than last resort" guidance.
- **Phase 2** — `frontend/css/style.css` — Replaced the `:root` palette with the spec's 7 design tokens (`--bg-base`, `--bg-panel`, `--ink`, `--calm`, `--stress`, `--anxiety`, `--recovery`) plus RGB-triplet companions for alpha-blended backgrounds/borders, and swept every hardcoded hex/rgba color in the file (~45 distinct literals) onto `var()` references — no color is hardcoded outside `:root` anymore. Imported JetBrains Mono + Sora via `@import` (kept CSS-only per the phase's file scope) and wired `--font-body`/`--font-mono`; numeric readouts (`.value`, breathing timers/cycle count/live HR, recovery countdown, prediction countdown, `rcHrChange`/`rcDurationVal`, instruction step badges) use `--font-mono`, everything else inherits Sora from `body`. No element moved, resized, or restructured. Deviations: (1) added supporting tokens beyond the official 7 — `--bg-elevated`, `--border`, `--muted`, `--accent` (aliased to `--recovery`) — since the app needs muted text/border/elevated-surface colors the reference list doesn't define; (2) the legacy `.state-active` class (unreachable — FSM normalizes ACTIVE to STRESS before the final state) is aliased to `--stress` instead of keeping its old stray purple hue, since ACTIVE has no dedicated token and this is more semantically correct; (3) threshold numbers embedded in mixed prose inside the interpretation table (e.g. "HR > baseline + 6 bpm") were left in Sora rather than JetBrains Mono, since isolating just the numeric substrings would require wrapping them in new HTML spans, which is out of scope for this CSS-only phase; (4) Chart.js canvas-rendered text (axis ticks, legend) still uses the browser default font since its font config lives in `app.js`, not `style.css` — flagging for whichever later phase next touches `app.js`.
- **Phase 3** — `frontend/index.html`, `frontend/css/style.css` — Restructured `.cards` into the target grid: state card at `2fr` beside a new `.side-cards` wrapper div (`1fr`) holding the Heart Rate and GSR cards stacked with `flex: 1` each, so the two together match the state card's height. Chart stays a full-width block below at a reduced `clamp(220px, 28vh, 260px)` height (was `clamp(205px, 30vh, 280px)`). Below 768px, `.cards` collapses to a single column, giving state → HR → GSR → chart in source order with no extra CSS needed since `.side-cards` is already a flex column internally. Bumped the mobile breakpoint from the pre-existing `760px` to the spec's `768px`. Calibration/prediction banners, breathing button, and evidence drawer were left untouched. Verified the grid at 1280/1024px, single-column stacking at exactly 768px and 600px, and zero horizontal overflow at all four widths — no deviations.
- **Phase 3B** — `frontend/index.html`, `frontend/css/style.css` — Added a circular `.state-ring` (inline SVG pulse-line icon + the existing `#stateVal`) with a `.state-divider` and four pre-rendered `.state-microcopy-lines` blocks (CALM/STRESS/ANXIETY/RECOVERY copy exactly as specified), shown/hidden purely via CSS keyed off the `.state-card.state-*` classes `app.js` already toggles — no JS was touched or needed. Added the subtitle "Based on real-time physiological signals.", heart/droplet SVG icons beside the HR/GSR labels, a 7-bar decorative `.mini-bar` plus fixed "Normal range · 60–100 bpm" / "Typical range · 100–1000 µS" reference text (static constants, not read from the SSE payload), and the "Physiological signals (real-time)" chart title. Verified in the browser across all three reachable live states (STRESS and ANXIETY via the mock cycle, CALM previously) plus the pre-calibration state, at both desktop and 375px — no overflow, no console errors, no new IDs added. Deviations: (1) no reference mockups were available this session, so the ring/divider/micro-copy layout (icon+state name inside a circular ring, divider, then copy to its right) is this session's interpretation of the spec's prose rather than a pixel match — worth a visual double-check against the actual mockups if/when available; (2) during calibration (no `state-*` class present yet) all four micro-copy blocks stay hidden rather than showing a placeholder, since the spec only defined copy for the 4 final states; (3) fixed the pre-existing `content: ";` malformed CSS on `.state-card::before` (flagged after Phase 1) while touching this exact block — it was silently dropping the per-state top accent bar, now restored to `content: "";`.
- **Phase 4** — `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js` — Added `#statusStrip` (new IDs `statusStrip`/`calibratedPill`/`calibratedDetail`; no existing IDs renamed) holding a new "✓ Calibrated / All systems operational" pill plus the existing `#predictionBanner` re-skinned in place as a second pill — same IDs (`predictionBanner`/`predictionTitle`/`predictionDetail`/`predictionCountdown`), only their CSS and the JS that fills them changed. `setCalibrationStatus()` now toggles `#calibrationBanner` (full banner, unchanged content/behavior during calibration) vs `#statusStrip` display based on `calibrated`, and fills `#calibratedDetail` from the same `baseline_hr`/`baseline_gsr` fields already used by the footer — no new SSE fields read. `updatePredictionBanner()` now has an `.is-idle` fallback: when `prediction.active` is false it shows a neutral "Next reading in ~1s / Collecting and analysing…" pill instead of hiding, but the countdown badge (`#predictionCountdown`) is only ever shown alongside a real `seconds_to_transition` value. The Calibrated pill is a real `<button>` with `aria-expanded`/click-to-toggle wired to `#calibratedDetail`. Verified the full lifecycle live in mock mode — calibrating → full banner, calibrated+idle → two neutral pills, calibrated+prediction-active → Calibrated pill + amber trending pill + distinct countdown badge — at 1280px and 375px (pills wrap to full-width stacked on mobile), with no console errors and no overflow. Deviations: (1) no reference mockups were available, so — per the spec's own tension between task 2 ("once calibrated, replace with a compact pill") and task 4's example neutral pair (which lists two alternative phrasings, one of which overlaps with task 2's exact wording) — the Calibrated pill's copy always follows task 2's literal wording, and task 4's neutral fallback is used only for the second (prediction) pill slot, avoiding a redundant pair of "systems operational" pills; (2) "Next reading in ~1s" is the sole idle-fallback string shown (not a live decrementing countdown), reflecting the backend's real, documented 1Hz SSE cadence rather than fabricating a countdown the server doesn't provide.
- **Phase 5** — `frontend/index.html`, `frontend/js/app.js` — Added `chartjs-plugin-annotation@3.0.1` via CDN (auto-registers on load — confirmed via `Chart.registry.plugins.get('annotation')`, no manual `Chart.register()` call needed). `render()` now compares each snapshot's `d.state` to the previous one and, on a genuine change (skipping the very first observed state, which isn't a "transition"), adds a dashed vertical line + colored label pill at that point's x-axis label via `addStateMarker()`, using the real Phase 2 design tokens resolved at runtime with `getComputedStyle` (`--calm`/`--stress`/`--anxiety`/`--recovery`) rather than hardcoded hex. `pruneStateMarkers()` runs on every tick right after the existing 60-point shift, deleting any marker (and its annotation config entry) whose label has scrolled out of `chart.data.labels` — verified live: after ~90s and 7 total transitions, only the 3 markers still in the visible window remained in both the tracking array and `chart.options.plugins.annotation.annotations` (no leak). Verified marker timestamps against the console's per-tick state log — they land exactly on the SSE sample where `state` actually changed. No changes to `.py` files or the SSE payload. No deviations.
- **Phase 6** — `frontend/index.html`, `frontend/css/style.css` — Replaced the full-width `.actions-bar` button with a `position: fixed; right:24px; bottom:24px` circular `.breathing-fab` (same `#manualBreatheBtn` ID and click handler, untouched in `app.js`) plus a `.breathing-fab-label` reading "Your wellbeing matters." beside it (hidden below 430px to avoid crowding the corner). Softened `.breathing-modal-backdrop` from `rgba(bg-base, 0.75)` + 4px blur to `0.45` + 2px blur so the dashboard stays legible behind the modal. Fixed the one amber holdout in the modal's palette: `.breathing-circle.hold` (the "Hold (Full)" phase) was using `var(--stress)` (amber) — changed to a dimmer `var(--calm)` glow so it reads as a paused continuation of the teal inhale phase instead of an alert color; exhale already used `var(--accent)` (=recovery indigo) and hold-empty already used `var(--muted)`, both already compliant. Left `.btn-danger` (Stop button) red, per the spec's explicit exception. The auto-prompt card (`#breathingPrompt`) was not touched. Verified the full flow live: FAB → modal open → duration select → Begin → Inhale/Hold/Exhale/Hold-Empty (teal → dim-teal → indigo → gray, no amber/coral) → Stop → recovery buffering (indigo spinner) → summary card, at both desktop and 375px, with the dashboard visibly legible behind the softened backdrop throughout. No console errors, no overflow, no deviations.
- **Phase 7** — `frontend/index.html`, `frontend/css/style.css` — Verified two of the three tasks were already fully satisfied by Phase 2's earlier sweep: Sora already cascades to all drawer/instructions prose via `body`'s `font-family` (no overrides anywhere else in the stylesheet), and the `.state-tag--*` pill colors already point at `var(--calm/--stress/--anxiety/--recovery)`. The only remaining work was JetBrains Mono for numeric thresholds specifically inside `.interpretation-table` (the decision table, not the whole drawer): wrapped the 6 numeric threshold phrases ("~30 seconds", "6 bpm", "40", "12 bpm", "80", "5 seconds") in `<span class="num">`, with no text content changed, and added one CSS rule (`.interpretation-table .num { font-family: var(--font-mono); }`). Verified drawer open/close and "How to use the device" expand/collapse are byte-identical in behavior, at 1280px and 375px (mobile card-style table layout unaffected), no console errors, no overflow. No deviations.
- **Phase 8** — `frontend/index.html`, `frontend/css/style.css` — Removed `.header-kicker` ("LIVE WELLNESS MONITOR", tracked-out uppercase chrome — exactly what the spec's task 3 excludes) entirely. Added a `.header-icon` inline SVG heartbeat/pulse line to the left of the title, and swapped `.sub`'s content from the old HC-05/fusion meta line to "Real-time monitoring for a healthier you."; the old meta text was moved verbatim to a new `.drawer-meta` paragraph as the evidence drawer's opening line (first element in `.guide-drawer-body`) — verified present and unchanged. Verified header height doesn't overlap the Phase 3 grid at 1280px, 375px, or with the status strip/prediction pill visible. Deviation: task 5 ("Keep the 'Calibrated' pill and 'Evidence' button in the header's right side") was not implemented as a literal relocation of `#calibratedPill` into the header — doing so would require new show/hide JS logic tied to the `calibrated` flag (the pill is currently only visible because it lives inside `#statusStrip`, whose visibility `app.js` already toggles; moving it out would make it permanently visible, including during calibration, unless something in `app.js` hides it directly), and this phase's file scope is `index.html`/`style.css` only, no `app.js`. Without reference mockups to confirm the intended header layout, relocating the pill risked a real correctness bug for an ambiguous cosmetic instruction, so the Calibrated pill was left in its working Phase 4 location; the header's right side keeps the "Method & evidence" button, satisfying that half of the task literally. Worth revisiting with the actual mockup and, if still wanted, a small `app.js` change in a later phase.
- **Phase 9** — `frontend/css/style.css`, `frontend/js/app.js` — Replaced the anxiety-only `state-pulse-red` keyframe with a single shared `state-pulse-glow` animation applied to all four reachable states plus the legacy `.state-active`, driven by a per-state `--pulse-glow-rgb` custom property (reuses the existing design tokens, no new colors). Duration is `var(--pulse-duration, 3s)`, nudged per tick by `updatePulseRate(d.hr)` in `app.js` (clamps 50-140bpm to a 4.2s-1.8s range) — pure cosmetic CSS-variable write, no state-reading logic touched. The crossfade (task 2) turned out to be mostly already in place from earlier phases (`.state-card`'s `transition: all 0.4s`, `::before`'s `background 0.4s`, `.state-ring`'s `border-color/color 0.4s` from Phase 3B) — the only gap was `.state` itself lacking a `color` transition, now added at 0.35s. Added a `prefers-reduced-motion: reduce` block disabling all four animated/transitioning selectors with `!important`, falling back to each state's static box-shadow. Verified live: pulse duration ties to HR (confirmed via computed style), no layout shift over time, crossfade transitions confirmed present on all four accent-carrying elements, reduced-motion rule confirmed parsed and well-formed (couldn't toggle the actual OS-level setting through the available browser tools, so verified by inspecting the parsed CSSOM rule instead of a live visual check). No overflow, no console errors. Deviation: interpreted the goal's "nothing else animates" together with task 4's "do not **add** any other animation" as scoping this phase's own additions, not as a retroactive mandate to strip out the small pre-existing animations from earlier phases (connection-dot pulse, banner slide-ins, breathing recovery spinner, etc.) — those weren't listed as this phase's files/tasks, and removing eight prior phases' reviewed, working polish without an explicit instruction seemed riskier than leaving them. Flagging this reading in case the actual mockup intends a stricter page-wide animation ban.
- **Phase 10 (final pass, closing out the redesign)** — `frontend/css/style.css` — Keyboard-focus audit found two elements whose `:focus-visible` rule removed the outline and replaced it with only a subtle hover-identical shadow/background bump: `.breathing-fab` and `.status-pill--calibrated`. Both now get a real outline ring (`3px solid var(--ink)` / `2px solid var(--calm)`) on top of their existing hover treatment — confirmed via real keyboard Tab navigation (not programmatic `.focus()`, which doesn't reliably trigger `:focus-visible` for a `<summary>`) that all of `.guide-toggle`, `.status-pill--calibrated`, `.breathing-fab`, `.instructions-toggle`, and the shared `.btn` base (Stop button, duration buttons) now show a clear, distinguishable focus state. Also added a `.instructions-toggle:focus-visible` rule, since it had been relying on the browser's thin default `outline: auto` — now `2px solid var(--accent)` with a negative offset so it isn't clipped by `.instructions`'s `overflow: hidden`. Re-verified responsive stacking at 1280/1024/768/320px with fresh page loads (no overflow at any width, including with the header icon, two-pill status strip, and FAB all present simultaneously) and re-ran the full Phase 0 regression checklist end to end in mock mode — calibration → status strip transition, SSE with no console errors, prediction pill active/idle states, full breathing flow (FAB → modal → phases → stop → recovery → summary), evidence drawer and "how to use" open/close all pass. Real-hardware verification (task 4) was not performed — no HC-05 device was available this session; flagging chart markers, the prediction pill, and the recovery card as the specific things worth re-checking against real (noisier) sensor data if/when hardware is available, per the spec's own guidance. Updated the README's "Frontend guide" section with a new "Design system" summary and refreshed the file/feature descriptions to match the redesigned UI, so it stays accurate for anything built on top of this later.

**Redesign complete.** All 10 phases landed with no unresolved regressions. Two things worth a human look given no reference mockups were available in this session: the Phase 8 deviation (Calibrated pill kept in the status strip rather than moved into the header) and the Phase 9 deviation (pre-existing minor animations from phases 1-8 were left in place rather than stripped page-wide) — both documented above with reasoning, both low-risk to revisit later if the actual mockups call for something different.

## Post-redesign fixes (reference mockup provided)

The user supplied the actual reference mockup after Phase 10 closed out, revealing two things to fix and resolving both open deviations above.

- **Full-width layout**: `.layout`'s `max-width` was `1180px`, leaving large empty margins on wide screens instead of the mockup's edge-to-edge feel. Raised to `1800px`.
- **State card**: rebuilt to match the mockup — `.state-ring` grew from a fixed 92px to `clamp(160px, 22vw, 260px)` (130px on phones), the icon changed from a pulse/ECG line to a two-hemisphere brain outline, and a new per-state caption (`.state-ring-caption`, e.g. "Elevated arousal detected" for STRESS) was added under the state name inside the ring — shown/hidden via the same `state-card.state-*` classes already used for the micro-copy, so no new JS. Fixed a follow-up mobile bug where the caption text overflowed the ring's circular border at 130px — added `max-width`, smaller font, and centered text, scoped tighter still below 430px.
- **Header/status-strip placement — resolves the Phase 8 deviation**: the mockup confirms the original spec's intent was to move the Calibrated pill into the header, which needed the `app.js` show/hide logic I'd flagged as out of scope for Phase 8. Moved `#calibratedPill` into a new `.header-actions` wrapper next to the renamed "Evidence" button (was "⌁ Method & evidence"; now "Evidence ›"), added `CALIBRATED_PILL.style.display` toggling in `setCalibrationStatus()` since it's no longer implied by `#statusStrip`'s own visibility. The bottom status strip's left pill is now a new, non-interactive "✓ Sensors connected / All systems operational" pill (`#sensorsPill`) instead of a second, redundant "Calibrated" pill — matching the mockup's two-pill bottom strip exactly and resolving the ambiguity between the spec's tasks 2 and 4 that Phase 4 had originally worked around.
- The Phase 9 deviation (pre-existing minor animations left in place) was not part of this feedback and remains unresolved — still worth a look if the mockup set has an opinion on it.

Verified live in mock mode: full lifecycle (calibrating → calibrated → prediction active/idle) at 1024px and 375px, evidence drawer open/close, no console errors, no horizontal overflow. Wide desktop widths (1280px+) were verified via `getBoundingClientRect()`/computed-style checks rather than screenshots — the browser automation pane in this session scales/crops screenshots inaccurately above roughly 1058px CSS width (a tooling quirk noted back in Phase 3), even though the underlying page renders correctly at those widths.

## Post-redesign fixes, round 2 (state/HR/GSR card sizing + cleanup)

Further user feedback against the reference mockup:

- **State card empty space**: `.state-card` grid-stretches to match `.side-cards`' height, but `.state-card-body` (the ring/divider/micro-copy row) wasn't set to fill that height, leaving dead space below the "Rules: ..." line whenever the state card ended up taller than its own content needed. Fixed by making `.state-card` a flex column and `.state-card-body { flex: 1 }`, so the ring/micro-copy row now centers within whatever height the grid gives the card — confirmed via `getBoundingClientRect()` that `.state-card` and `.side-cards` report identical heights with no visible gap.
- **Ring size**: reduced from `clamp(160px, 22vw, 260px)` to `clamp(140px, 16vw, 200px)` per the request to size it down a bit, now that the empty-space fix means a smaller ring no longer leaves a gap.
- **HR/GSR cards restructured to match the reference**: was a vertical stack (icon+label, then value, then unit below it, then a full-width mini-bar, then range text below that). Now a horizontal split via a new `.metric-row` — value+unit on the left (`.metric-value`), a compact sparkline + right-aligned two-line range text on the right (`.metric-range`) — matching the reference image's layout. Also changed the GSR unit label from "raw units" to "µS" next to the number, consistent with the range text's own units (already "µS" since Phase 3B, following the original spec's wording) and matching the reference image. The mini-bar's tallest bar is now tinted `var(--accent)` instead of uniform gray, matching the reference's single highlighted bar.
- **Removed the "Sensors connected" pill** (`#sensorsPill`) entirely, per direct feedback that it was redundant with the header's "Calibrated" pill — `#statusStrip` now holds only the prediction/idle pill. Removed its now-dead `.status-pill--sensors` CSS too.

Verified live in mock mode at 1024px and 375px: no dead space in the state card, HR/GSR cards match the reference layout, sensors pill gone with no layout gap left behind, no console errors, no horizontal overflow.

## Post-redesign fixes, round 3 (calibrating-state redesign)

User feedback (with a screenshot of the CALIBRATING view): large empty space next to the ring, and the word "CALIBRATING" visually overlapping the brain icon above it. Root cause: the calibrating state was rendered with no dedicated CSS state class (`app.js` passed `cls = ""`), so none of the per-state caption/microcopy rules matched — the ring showed only the icon and the raw state word at the same oversized font used for "CALM"/"STRESS" (`clamp(1.4rem, 2.6vw, 2.1rem)`), which is too wide for "CALIBRATING" to fit on one line inside a 140–200px circle, and the microcopy column next to it stayed blank because no `.state-microcopy--calibrating` variant existed.

Rather than patch the symptom, gave calibrating its own first-class state, matching the same visual treatment CALM/STRESS/ANXIETY/RECOVERY already get:

- **New `state-calibrating` class**: `app.js` now sets `state-calibrating` on `#stateCard` (instead of no class) while `!d.calibrated`. It gets the full existing state-card treatment for free — accent-colored border, top accent bar, and the ambient `state-pulse-glow` box-shadow animation (added to that animation's selector list) — so it now reads as a real state, not a blank fallback.
- **Circular progress ring**: added an SVG ring overlay (`.state-ring-progress`, two concentric `<circle>`s — a static track and an animated `stroke-dashoffset` fill) inside `.state-ring`, hidden (`opacity: 0`) except in `.state-calibrating`. Progress is driven by the already-exposed `window_samples` SSE field against the known ~30-sample baseline window (`CALIBRATION_TARGET_SAMPLES = 30`, matching the existing "first 30 seconds" copy elsewhere on the page and `ANXIETY_BASELINE_CALIBRATION_S`'s default) — no backend changes needed.
- **Fixed the text overlap**: added a `.state--compact` modifier (`clamp(0.92rem, 1.5vw, 1.15rem)`) that `app.js` toggles on `#stateVal` only while calibrating, so "CALIBRATING" sizes down to fit cleanly inside the ring instead of wrapping/overlapping the icon.
- **Filled the empty space**: added a `state-ring-caption--calibrating` caption ("Establishing baseline · NN%", live-updated from the same progress value) and a `state-microcopy--calibrating` three-line block ("Sit still and relax." / "Reading your baseline HR & GSR." / "Prediction starts automatically.") using the exact same caption/microcopy pattern the other four states already use — no new layout primitives.
- **Subtle motion cue**: the brain icon now has a slow opacity/scale pulse (`state-ring-icon-pulse`) only while calibrating, signalling "in progress" without adding a second animation loop (disabled under `prefers-reduced-motion`, alongside the existing pulse-glow opt-out).

Verified live in mock mode: reloaded during the ~30s mock calibration window and watched the ring fill from a live percentage (screenshotted at 43% and 60%) with the caption and microcopy rendering correctly, no overlap with the icon; confirmed the ring/glow/caption cleanly revert to the normal CALM look the instant `calibrated` flips true; checked 1024px and 375px widths with no console errors and no horizontal overflow.

## Post-redesign fixes, round 4 (centered state indicator + creative copy treatment)

User feedback: on a full desktop-width screen the state card still felt empty, with two concrete asks — (1) center the actual state indicator (the ring) in the box, and (2) make the supporting text more visible/creative instead of the current plain small copy.

Root cause of the "empty" feeling: `.state-card-body` was a flex *row* — ring pinned to the left, a 1px vertical divider, then a `flex:1` text column filling whatever width was left. On the 2fr grid column at desktop widths that remainder was 400–600px of near-empty space holding three short lines of small muted text, so the box read as unbalanced and sparse no matter how tall it was.

Redesigned as a single centered vertical group instead of a left/right split:

- **`.state-card-body` is now a centered flex column** (`flex-direction: column; align-items: center; justify-content: center;`) instead of a row, so the ring is the true horizontal *and* vertical center of the box — confirmed via `getBoundingClientRect()` at 1440px width: ring and quote-card center X both land at 480.9px against a card center X of 480.9px, and the ring+quote group sits with only 4px of padding above/below inside a 460px-tall card (matching `.side-cards`' height exactly).
- **The old vertical divider became a short horizontal accent line** (`.state-divider`, 36×3px, rounded) centered under the ring, reading the same `--pulse-glow-rgb` custom property the state-color system already sets per state — so it re-colors automatically with no new per-state selectors.
- **The microcopy became a "quote card"** instead of plain floating text: `.state-microcopy-lines` now renders as a rounded, tinted panel (background/border at low-alpha `--pulse-glow-rgb`, so it also auto-recolors per state) with a large decorative opening-quote glyph (`::before`, CSS `“`) in the top-left corner, and its first line is wrapped in a new `.state-microcopy-lead` span styled bold/larger (`1.1rem`/700 weight, full `--ink` contrast) so each state's headline ("All steady.", "Breathe.", "You're safe.", "Good work.", "Sit still and relax.") reads as a real callout instead of blending into the two supporting lines below it.
- No HTML structure was added beyond the one `<span class="state-microcopy-lead">` wrapper per existing microcopy line (five total, one per state including calibrating) — the calibrating state's progress ring, live percentage caption, and pulse animation from round 3 are untouched and inherit the new centered layout and quote-card styling automatically.

Verified live in mock mode: confirmed centering with `getBoundingClientRect()` at 1440px (screenshots are unreliable above ~1058px CSS width per the existing browser-pane caveat below); screenshotted the CALM, STRESS, and CALIBRATING states at 1024px showing the centered ring, colored accent line, and quote card with visible lead line and quote glyph; confirmed calibrating's live percentage and progress ring still update correctly inside the new layout; checked 375px mobile with no overflow and no console errors.

## Round 5 (rebrand, viewport-fit layout, richer HR/GSR cards)

User asks, in one message: shrink the state box so the whole graph is visible without scrolling; make the "Evidence" button match the "Calibrated" pill's size; rename the app to **SAARTHI — Real-Time Physiological Stress & Anxiety Monitoring with Early Intervention**; make better use of the empty space in the HR/GSR cards (bigger range/sparkline area); redesign the three stacked banners above the cards (connection status, prediction, calibration/breathing alerts) to use space more smartly; and enlarge the chart. Measured with `getBoundingClientRect()` at 1440×900 before touching anything: the state/HR/GSR row alone was 460px tall, the chart was only 252px, and the page needed 1153px of an 900px viewport (253px of forced scrolling) — confirming the state card's excess height was the main reason the graph never fit on screen.

- **Rebrand**: `<title>`, the header `<h1>`, and its subtitle now read "SAARTHI" / "Real-Time Physiological Stress & Anxiety Monitoring with Early Intervention" (was "Anxiety Monitor" / "Physiological state" / "Real-time monitoring for a healthier you."). Left the "Current physiological state" card heading alone since that names the card's content, not the product.
- **Evidence button sizing**: `.header-actions` changed from `align-items: center` to `align-items: stretch`, so `#guideToggle` (a plain single-line button) automatically grows to match `#calibratedPill`'s natural two-line height (55px) via ordinary flex stretch — no hardcoded height, and it still collapses to its own intrinsic size when the pill is hidden pre-calibration.
- **Merged the three status banners into one row**: `#connBar`, `#calibrationBanner`, and `#statusStrip` are now children of a single `.status-row` flex container instead of three stacked full-width blocks. Connection becomes a compact fixed-width pill (`flex: 0 0 auto; max-width: 230px`, text ellipsized) sitting beside whichever of the calibration banner or prediction strip is active (`flex: 1`), collapsing to a column only under 700px. Combined with trimmed padding on `.calibration-banner`, `.prediction-banner`, and `.breathing-prompt`, this took the connection+status area from ~117px of stacked height down to ~55–65px.
- **Shrunk the state card's internal sizing** (ring `clamp(140px,16vw,200px)` → `clamp(118px,13vw,164px)`, icon and state-text clamps scaled down to match, quote-card padding and gaps trimmed) so the state/HR/GSR row dropped from 460px to 393px — still centered and legible, just not oversized relative to its neighbors.
- **HR/GSR cards redesigned around a taller, real-data mini-chart** instead of a small decorative corner sparkline: each card is now a flex column (icon+title → value+trend badge → a full-width live sparkline → range note) so the card's height is actually used. The mini-bar's 8 bars are now driven by a rolling 8-sample history of real HR/GSR values (`hrHistory`/`gsrHistory` in `app.js`, normalized min–max per bar) instead of a fixed decorative shape, and a new `.metric-trend` badge (↑ Rising / ↓ Falling / → Steady, color-coded stress-orange/calm-green/muted) is computed by comparing the latest reading against the value ~6 samples back (`updateTrend()`), giving each card a small real insight instead of blank padding.
- **Chart enlarged**: `.chart-wrap` height went from `clamp(220px, 28vh, 260px)` to `clamp(270px, 36vh, 360px)`, and assorted vertical margins/paddings (`.layout`, `.header`, `.footer`, `.instructions`) were trimmed by a few px each to make room without cutting into the cards or chart.

Verified live in mock mode at 1440×900: with no transient alert banner showing, the header through the full chart now ends at 885px — inside the 900px viewport with zero scrolling required to see the complete graph (previously the graph's bottom edge was at 1039px, i.e. permanently below the fold on a 900px-tall window). Only the collapsed "How to use the device" accordion and the small debug footer line (baseline/window-samples text) fall below the fold, which is expected and low-priority. Also confirmed: the Evidence button visually matches the Calibrated pill's height; the HR/GSR mini-bars and trend badges respond live to rising/falling mock data (screenshotted both a "↓ Falling" and "↑ Rising" state); checked 1024px and 375px widths with no console errors, no horizontal overflow, and no dead/empty space reappearing in the state card at the new smaller ring size.
