# Testing and verification

Manual checks run against a live server before a change is considered done.
There is no automated test suite in this repository; these are the procedures
that have actually been used, and the mock scenarios exist so they can be run
without hardware.

---

## UI Regression Checklist

Re-run in mock mode (`ANXIETY_USE_MOCK_SERIAL=1`, `python app.py`) after every UI redesign phase.

- [x] Calibration → normal display works (banner transitions from calibrating to prediction-active; state card shows live FSM state after ~30s)
- [x] SSE updates every second with no browser console errors
- [x] Prediction banner appears when `prediction.active` is true and disappears when it clears
- [x] Full breathing exercise flow: prompt or manual button → modal → duration select → phases → stop → recovery countdown → summary card
- [x] Explanation drawer (`How it works & Evidence`) opens and closes
- [x] Drawer tabs switch between `System walkthrough` and `Research & evidence`, and reopen on the walkthrough
- [x] "How to use the device" expands and collapses
- [x] No horizontal scrollbar at desktop (~1280px) and ~1024px widths (added in Phase 1+)

**Phase 0 baseline (2026-09-11):** git tag `ui-redesign-phase-0-baseline` on commit `af1a187`. All checklist items above verified passing in mock mode except the horizontal-scroll item (not yet in scope).

## Verifying states without hardware

`python app.py --scenario <name>` replays a scripted physiological scenario
through the real pipeline, so every state and pattern can be demonstrated and
re-checked with no device attached. See "Run in mock mode" in the
[README](../README.md) for the scenario table and the `demo` timeline.

| To verify | Scenario | Watch for |
| --- | --- | --- |
| Calibration and CALM | `calm` | Baseline locks in ~30 s; Calibrated pill appears |
| STRESS band | `stress` | FSM reaches STRESS ~40 s after the ramp starts |
| ANXIETY and alerts | `anxiety` | FSM reaches ANXIETY and holds; alert + intervention offer |
| Activity rejection | `activity` | Rules report ACTIVE, not ANXIETY, on an HR-only rise |
| Recovery path | `recovery` | ANXIETY → RECOVERY → CALM (RECOVERY shows ~5 s by FSM design) |
| Everything, unattended | `demo` (default) | Full arc plus every pattern label, looping |

## Backend spot-check

`python -c "import app"` and `python -m compileall backend` catch import and
syntax breakage. The pipeline itself can be exercised offline by feeding the
mock generator's phases straight through
pipeline → features → rules → fusion → smoother → FSM, which is how the
scripted scenarios above were validated to reach each state.
