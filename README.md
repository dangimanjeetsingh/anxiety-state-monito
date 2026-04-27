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

### 13. Snapshot, logging, and serving

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
| `backend/state_service.py` | Main orchestrator, logging layer, and JSON snapshot provider |
| `backend/flask_app.py` | Web routes, CORS, SSE, and static frontend serving |

## Frontend guide

The frontend is a static dashboard served directly by Flask from the `frontend/` directory.

### Files

| File | Responsibility |
| --- | --- |
| `frontend/index.html` | Layout, cards, chart canvas, status bar, and device instructions |
| `frontend/js/app.js` | SSE subscription, DOM updates, chart updates, and connection UI logic |
| `frontend/css/style.css` | Dashboard styling, state colors, status indicators, and instructions panel |

### What the frontend displays

- Current HR
- Current GSR
- Final state
- Rule state / ML state / fusion source text
- Connection state
- Sensor warning banner
- Baseline summary
- Window sample count and calibration flag
- Live chart with the latest 60 points

### Important UI details

- The frontend subscribes to `/stream` using Server-Sent Events (SSE)
- The chart is powered by Chart.js from a CDN
- HR is charted directly
- GSR is charted as `GSR / 4` to keep both traces visible on one chart
- The UI still contains an `ACTIVE` visual class, but the final FSM state normally emits `CALM`, `STRESS`, `ANXIETY`, or `RECOVERY`
- If the stream fails, the UI shows a connection warning and retries after `3s`

### Data returned by the backend but not currently rendered in the dashboard

- `features`
- `pattern`
- `alert`

Those fields are already available through the JSON API, so the UI can be expanded later without changing the backend contract.

## API contract

### `GET /`

Serves the static frontend dashboard.

### `GET /data`

Returns the latest snapshot as JSON and disables caching via headers.

### `GET /stream`

Returns an SSE stream. The server emits one JSON payload per second.

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

### Example JSON payload

```json
{
  "server_time": 1760000000.0,
  "hr": 73.4,
  "gsr": 512.7,
  "state": "STRESS",
  "rule_state": "STRESS",
  "ml_state": "ANXIETY",
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
  "alert": "LOW"
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

Mock mode generates a repeating cycle with:

- calm period
- stress build
- anxiety peak
- recovery period
- random noise and occasional spikes

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
