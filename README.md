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

## Documentation

This README is the project specification: what the system is, how to run it,
how it is configured, and where its limits are. The detail lives next to it.

| Document | What is in it |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The runtime pipeline stage by stage, backend module guide, frontend guide, HTTP/SSE contract, session lifecycle and report, CSV schema, ML pipeline |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Development journal: UI redesign phases, post-redesign rounds, accuracy corrections found in review, pre-freeze reliability pass |
| [docs/TESTING.md](docs/TESTING.md) | Manual regression checklist and how to verify each state without hardware |

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

### Capabilities

| Capability | Summary |
| --- | --- |
| Personal baseline | Every reading is judged against a resting HR/GSR measured over the first ~30 s of the session, not against fixed thresholds |
| Two-tier inference | Deterministic rules (Tier 1) reconciled with a RandomForest (Tier 2); the model corroborates rather than overrides severity |
| Stabilised output | Majority vote over the last N labels, then an FSM with per-transition hold times, so the state cannot flicker |
| Early warning | Short-horizon projection of the stress trend, surfaced as a countdown pill before the state changes |
| Guided intervention | A 4-4-4-4 breathing exercise, offered on rising arousal, with measured HR/GSR recovery afterwards |
| Sessions and reports | Start/end a session; get time-in-state, episodes, early-warning hit rate and interventions as JSON, HTML or CSV |
| Hardware-free demo | Scripted mock scenarios reproduce every state and pattern through the real pipeline |

Each of these is specified in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

## Repository structure

```text
project-code/
+-- app.py                     entry point (`python app.py [--mock] [--scenario N]`)
+-- backend/
|   +-- alert_system.py        alert level from state + pattern + confidence
|   +-- bt_reader.py           serial ingestion, and the scripted mock generator
|   +-- config.py              every tunable, all env-overridable
|   +-- features.py            baseline tracking + 30 s window feature vector
|   +-- flask_app.py           HTTP routes and the SSE stream
|   +-- fusion.py              rule / ML reconciliation
|   +-- ml_predictor.py        Tier 2 RandomForest wrapper
|   +-- paths.py               repo-relative path resolution
|   +-- pattern_detector.py    temporal patterns over ~60 s
|   +-- pipeline.py            validation, smoothing, sliding window
|   +-- prediction_smoother.py majority vote + hysteresis
|   +-- report_render.py       session report as HTML / CSV
|   +-- rules.py               Tier 1 threshold classifier
|   +-- session_manager.py     session lifecycle state machine
|   +-- session_recorder.py    per-session accumulation and checkpoints
|   +-- state_machine.py       FSM with hold times
|   +-- state_service.py       orchestration + snapshot the API serves
|   `-- trend_predictor.py     short-horizon early warning
+-- frontend/
|   +-- css/style.css
|   +-- js/app.js
|   `-- index.html
+-- ml/
|   +-- data/training_data.csv
|   +-- model.pkl
|   +-- scaler.pkl             present but unused — see the changelog
|   `-- train.py
+-- data/
|   +-- logs/physio_log.csv    append-only sample log
|   `-- sessions/              per-session report JSON (runtime, gitignored)
+-- docs/
|   +-- ARCHITECTURE.md
|   +-- CHANGELOG.md
|   `-- TESTING.md
+-- requirements.txt
`-- various debug and diagnostic artifacts
```

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
python app.py --mock
```

Equivalent: `$env:ANXIETY_USE_MOCK_SERIAL="1"; python app.py`.

Mock mode uses the **same pipeline as hardware**. `BluetoothReader` emits synthetic lines at 1 Hz through the identical parse → pipeline → classify path — only the source of the samples changes.

#### Scenarios

The generator replays a **scripted scenario**, chosen with `--scenario NAME`
(or `ANXIETY_MOCK_SCENARIO`). Every elevated phase is held for longer than the
30 s feature window on purpose: `compute_features()` compares the *window mean*
to the baseline, so a short spike can only ever raise the mean by a few bpm and
can never clear the ANXIETY thresholds. The old 30 s sine cycle topped out at
STRESS for exactly that reason.

| Scenario | Length | What it demonstrates |
| --- | --- | --- |
| `demo` (default) | ~7 min, loops | The full arc: CALM → STRESS → ANXIETY → RECOVERY → CALM → ACTIVE → CALM, plus every pattern label |
| `calm` | continuous | Steady baseline / calibration |
| `stress` | ~2.5 min | STRESS band only, held |
| `anxiety` | ~4 min | Fast route to ANXIETY, then held for ~3 min |
| `activity` | ~2.5 min | Motor activity: HR climbs, GSR flat → `ACTIVE` rule (the false-alarm rejection story) |
| `recovery` | ~4.5 min | ANXIETY → RECOVERY → CALM, including the post-arousal undershoot |

```powershell
python app.py --scenario anxiety      # jump straight to a held ANXIETY state
python app.py --scenario activity     # show movement being rejected, not alarmed
python app.py --mock --speed 1.5      # compress the script (see caveat below)
```

`--speed N` (or `ANXIETY_MOCK_SPEED`) compresses the script's clock. Keep it at
or below ~1.5: past that the plateaus fall inside the 30 s averaging window and
the deltas stop reaching their bands. `ANXIETY_MOCK_LOOP=0` holds the final
phase instead of repeating the script.

#### `demo` timeline (after the ~30 s calibration warmup)

| Phase | Duration | HR / GSR vs baseline | Expected dashboard state |
| --- | --- | --- | --- |
| calm | 45 s | +0 / +0 | CALM |
| onset | 25 s | → +10 / +55 | CALM → STRESS, `GRADUAL_STRESS_BUILD`, early-warning banner |
| stress | 45 s | +10 / +55 | STRESS |
| escalation | 16 s | → +42 / +230 | `RAPID_STRESS_SPIKE`, STRESS → ANXIETY |
| anxiety | 90 s | +42 / +230 | ANXIETY (alerts, interventions) |
| deescalate + rebound | 12 s + 40 s | → −9 / −70 | ANXIETY → RECOVERY → CALM, `SLOW_RECOVERY` |
| recovery + settled | 75 s + 30 s | → +0 / +0 | CALM |
| activity + cooldown | 45 s + 35 s | HR → +30, GSR ≈ flat | `ACTIVE` rule (HR rise without a GSR surge) |

Timings are the *input* script; the displayed state trails it by roughly one
feature window plus the smoother and FSM hold timers (about 10–20 s), which is
the same lag real hardware shows. RECOVERY is visible for about 5 s — that is
the FSM's own hold logic, not the generator.

Noise is Gaussian and small (σ ≈ 1.2 bpm / 5 GSR units) so feature confidence
stays around 0.8–0.99 and the rules' low-confidence downgrade never fires
during a demo.

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
| `ANXIETY_MOCK_SCENARIO` | `demo` | Scripted mock scenario: `demo`, `calm`, `stress`, `anxiety`, `activity`, `recovery` |
| `ANXIETY_MOCK_SPEED` | `1.0` | Time compression for the mock script (keep ≤ ~1.5) |
| `ANXIETY_MOCK_LOOP` | `True` | Repeat the scenario instead of holding its last phase |

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

### Session and report settings

| Variable | Default | Purpose |
|---|---|---|
| `ANXIETY_CALIB_STALL_FACTOR` | `2.0` | Multiple of the calibration window after which calibration is reported as stalled |
| `ANXIETY_SESSION_CHECKPOINT_S` | `10.0` | Seconds between `.partial.json` checkpoint writes |
| `ANXIETY_SESSION_AUTOSTART` | `false` | Start a session automatically on boot (exhibition convenience) |

---

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
