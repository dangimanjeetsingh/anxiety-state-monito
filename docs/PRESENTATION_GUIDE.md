# Presentation guide — Innovision 2026

Everything needed to build the 9-slide deck for the judging panel, using the
official template `Format PPT -Innovision-2026.pptx`.

This is written for whoever is making the slides, including someone who did not
write the code. Each slide below gives: **what the judges expect**, **content
you can paste straight in**, **what to leave out**, **what visual to use**, and
**a 45–60 second speaker script**.

At the end there is a screenshot shot-list, a live-demo runbook, and a bank of
likely judge questions with answers.

> **The one rule that matters more than any other:** do not put "95.7% accuracy"
> on a slide. Read [§ The accuracy claim](#the-accuracy-claim-read-this-before-writing-any-slide)
> before writing anything.

---

## Contents

- [The template's own rules](#the-templates-own-rules)
- [The accuracy claim — read this before writing any slide](#the-accuracy-claim-read-this-before-writing-any-slide)
- [Slide 1 — Title](#slide-1--title)
- [Slide 2 — Introduction](#slide-2--introduction)
- [Slide 3 — Software / Hardware Requirement](#slide-3--software--hardware-requirement)
- [Slide 4 — Problem Statements](#slide-4--problem-statements)
- [Slide 5 — Preliminary Design / Flowchart](#slide-5--preliminary-design--flowchart)
- [Slide 6 — Project Implementation and Real Time Example](#slide-6--project-implementation-and-real-time-example)
- [Slide 7 — Innovation / Novelty](#slide-7--innovation--novelty)
- [Slide 8 — Future Scope](#slide-8--future-scope)
- [Slide 9 — Thank You / Queries](#slide-9--thank-you--queries)
- [Screenshot shot-list](#screenshot-shot-list)
- [Live demo runbook](#live-demo-runbook)
- [Judge Q&A bank](#judge-qa-bank)
- [Numbers you may quote, and their source](#numbers-you-may-quote-and-their-source)
- [Final checklist](#final-checklist)

---

## The template's own rules

Taken from the supplied file. Follow them exactly — panels notice.

| Rule | Detail |
| --- | --- |
| **Slide count** | Exactly 9, in the given order. Do not add or reorder slides. |
| **Body text** | 20 pt Calibri, as stated on every content slide |
| **Footer** | Department name on every slide |
| **Page numbers** | Already in the template — keep them |
| **Title slide fields** | Project Title · Presented by · Project ID · Student Names–UIDs |

**What 20 pt Calibri actually means for you:** roughly **6 bullet lines per
slide, 10–12 words each**. That is the real constraint of this deck. Every slide
below is written to fit it. If a slide feels thin, the fix is a *diagram*, not
more text — the detail belongs in your mouth, not on the wall.

---

## The accuracy claim — read this before writing any slide

The dashboard's own research panel displays **95.78% accuracy**. That number is
real but it is measured on a **leaky split**, and a sharp judge will catch it.

Here is why, in plain terms. The model learns from 30-second windows sampled once
per second, so two consecutive rows share 29 of their 30 underlying readings —
they are almost the same row. The training script shuffles rows randomly before
splitting into "train" and "test", so nearly every test row has a near-twin in
the training set. The model is being tested on data it has effectively already
seen. That measures memorisation, not skill.

When the same model is tested honestly:

| How it was tested | Accuracy | What it means |
| --- | --- | --- |
| Random row split (the 95.78% figure) | **95.78%** | Leaky — an upper bound, not a result |
| Chronological split (train on early, test on later) | **48.5%** | Coin-flip on genuinely unseen time |
| Grouped by label block, 4-fold | **72.8%** average (44.6–88.4%) | The most honest of the three |

The dataset has no subject or session column, so a proper subject-independent
test is not even possible with it.

**How to present this — and this is a strength, not a weakness:**

> "Our model reports 95.8% on a random split, but we found that split is leaky —
> consecutive windows overlap by 29 of 30 samples. Tested chronologically it
> drops to 48.5%, and grouped by label block it averages 72.8%. So we do not
> claim the high number. We treat the ML tier as a **second opinion only**: it
> can confirm the rule engine but is not allowed to overrule it. The states you
> see on the dashboard are decided by transparent physiological thresholds."

Judges reward a team that audits its own result far more than one that quotes a
number it cannot defend. **Put the honest framing on slide 7 (Innovation) as a
rigour point.** Do not hide it and do not lead with it.

---

## Slide 1 — Title

**Fill in the template fields:**

- **Project Title:** Saarthi — Real-Time Physiological Stress & Anxiety
  Monitoring with Early Intervention
- **Presented by:** [names]
- **Project ID:** [as allotted]
- **Student Names–UIDs:** [as allotted]

**Optional one-line tagline under the title** (fits the template, adds a lot):

> A wearable that detects rising anxiety from heart rate and skin response —
> and intervenes before it peaks.

**Speaker script (~20 s):** "Good morning. Our project is Saarthi, a real-time
anxiety monitoring system. It reads two physiological signals from a wearable,
learns each person's own resting baseline, and warns them *before* stress
becomes anxiety — then guides them through a breathing exercise and measures
whether it worked."

---

## Slide 2 — Introduction

**Purpose:** what the system is and what it does. No problem statement here —
that is slide 4. Keep them distinct or you will repeat yourself.

**Content to paste:**

- Wearable device reads **heart rate (HR)** and **galvanic skin response (GSR)**
  once per second over Bluetooth
- The system learns the **user's own resting baseline** in the first ~30 seconds
- Every reading is judged **relative to that personal baseline**, not fixed limits
- Two independent methods decide the state: **rule-based thresholds + a trained
  ML model**
- Output states: **CALM → STRESS → ANXIETY → RECOVERY**, shown live on a
  dashboard
- Includes **early warning**, a **guided breathing intervention**, and an
  automatic **session report**

**Leave out:** module names, file names, code, thresholds. Too early.

**Visual:** the device photo, or the dashboard in its CALM state.

**Speaker script (~50 s):** "The device measures two signals — heart rate, and
galvanic skin response, which is how well the skin conducts a small current.
Sweat glands react to stress before you consciously notice it, and sweat
conducts, so GSR rises early. Both are sampled once a second and sent over
Bluetooth. The first thirty seconds are spent learning *your* resting normal —
because a resting pulse of 55 and one of 85 are both healthy, and only the
change from your own normal means anything. After that, every reading is scored
against that baseline by two independent methods, and the result is one of four
states shown live."

---

## Slide 3 — Software / Hardware Requirement

**Purpose:** prove the build is real and specified. Judges scan this for
competence. Use two columns.

**Hardware** — *confirm the exact part numbers with your hardware member before
printing:*

- Microcontroller: [CONFIRM — e.g. Arduino Uno / Nano]
- Pulse / heart-rate sensor: [CONFIRM — e.g. MAX30102 or analog pulse sensor]
- GSR (EDA) sensor with two skin electrodes: [CONFIRM]
- **HC-05 Bluetooth module** — serial link to the host at 9600 baud
- Buzzer — 2 beeps on boot, 1 beep per sample recorded
- Power supply / battery, wearable strap
- Host laptop running the dashboard

**Software**

- **Python 3** — backend
- **Flask + Flask-CORS** — web server and live stream
- **scikit-learn** (Random Forest), **NumPy**, **pandas**, **joblib** — ML tier
- **pyserial** — Bluetooth serial input
- **HTML / CSS / JavaScript + Chart.js** — dashboard
- Arduino IDE / [CONFIRM] for the device firmware

**Add one line the judges like:** "No database and no cloud service — the system
runs entirely on one laptop; all data stays local."

**Speaker script (~40 s):** "On the hardware side, a pulse sensor and a GSR
electrode pair feed a microcontroller, which streams readings over an HC-05
Bluetooth module at one sample per second, with a buzzer confirming each sample.
On the software side, the backend is Python — Flask serves the dashboard and
streams live updates, and scikit-learn provides the machine-learning tier. The
front end is plain HTML, CSS and JavaScript with Chart.js. There is no database
and no cloud dependency; everything runs locally, so no physiological data
leaves the machine."

---

## Slide 4 — Problem Statements

**Purpose:** why this needs to exist. Give the panel a reason to care, then the
technical problems your design had to solve. Two halves.

**The human problem**

- Anxiety escalates **before the person consciously notices** it
- Most tools are **retrospective** — they tell you afterwards, when it is too late
- Generic thresholds fail: one person's normal pulse is another's alarm

**The technical problems this created**

- **Physical movement mimics anxiety** — both raise heart rate
- **Raw sensor data is noisy** — a single bad reading must not trigger an alarm
- **A dashboard that flickers between states is useless** and destroys trust
- Any alert must be **explainable**, not "the AI said so"

**Speaker script (~50 s):** "The core problem is timing: by the time someone
realises they are anxious, the episode is already underway. Most wearables
report afterwards. We wanted to intervene during the rise. That created three
engineering problems. First, movement raises heart rate exactly like anxiety
does, and our device has no accelerometer. Second, sensor data is noisy — a
single spike must never trigger an alarm. Third, a state display that flickers
between calm and anxious is worse than no display, because nobody trusts it.
Every design decision in the project is an answer to one of those three."

---

## Slide 5 — Preliminary Design / Flowchart

**Purpose:** the architecture slide. **This slide should be almost entirely a
diagram.** Judges form their opinion of technical depth here.

**Draw this as boxes and arrows** (build it in PowerPoint shapes, do not paste
text):

```
  SENSOR (HR + GSR, 1 Hz)
        ↓  Bluetooth HC-05
  1. READ      →  parse the line, discard junk
        ↓
  2. VALIDATE  →  reject impossible values, smooth over 3 readings
        ↓
  3. CALIBRATE →  learn the personal baseline (first ~30 s)
        ↓
  4. MEASURE   →  30-second window → 10 features
        ↓            (delta HR, delta GSR, trends, confidence)
        ↓
  5. DECIDE    →  RULES (Tier 1)  +  ML MODEL (Tier 2)
        ↓                ↓              ↓
  6. FUSE      →  rules win ties; ML confirms, cannot overrule
        ↓
  7. STABILISE →  majority of last 7  →  state machine hold times
        ↓
  8. OUTPUT    →  CALM / STRESS / ANXIETY / RECOVERY
        ↓
  9. ACT       →  early warning · breathing exercise · session report
```

**Add the state machine as a small inset** — it is the most impressive single
diagram in the project:

```
   CALM ──3s──► STRESS ──3s──► ANXIETY
     ▲            │                │
     └────3s──────┘                │ 5s (needs falling HR)
     ▲                             ▼
     └──────────5s──────────── RECOVERY
```

**Caption under it (one line, 20 pt):** "Every transition needs its condition to
hold for a minimum time — the state cannot flicker, and ANXIETY can only be left
through RECOVERY."

**Speaker script (~60 s):** "This is the full pipeline. A reading is parsed,
range-checked and smoothed, then measured against the personal baseline over a
30-second window that produces ten features. Two independent decision-makers see
those features — a transparent rule engine and a Random Forest. Their verdicts
are fused, with the rules taking priority. That verdict then has to survive two
more filters: a majority vote over the last seven readings, and this state
machine, where every transition needs its condition held for three to five
seconds. The result is that a single odd reading cannot change the display, and
anxiety can only be left through a recovery phase — which is how the body
actually behaves."

---

## Slide 6 — Project Implementation and Real Time Example

**Purpose:** proof that it works. Screenshots + one worked timeline. This is the
slide the judges remember.

**Left half — dashboard screenshot** in the ANXIETY state (red state card, alert
visible).

**Right half — the real timeline** (a genuine run, not invented):

| Time | The body | The system |
| --- | --- | --- |
| 0 s | HR and GSR begin rising | Nothing yet — the 30 s average has barely moved |
| ~10 s | Still rising | **Early warning** appears with a countdown |
| ~25 s | HR +7, GSR +35 | Commits to **STRESS** |
| ~48 s | HR +15, GSR +90 | Commits to **ANXIETY**, alert HIGH, breathing offered |
| ~2 min | Person calms, HR falling | **RECOVERY** |
| ~2 min 10 s | Settled | **CALM** — never straight from anxiety |
| End | Session ends | Report: time per state, episodes, warning hit rate |

**One line to include, in bold:** "Demonstrated live using a scripted data
generator that reproduces every state through the real pipeline — no hardware
and no distressed person required."

**Speaker script (~60 s):** "Here is an actual episode. At ten seconds, before
any state has changed, the trend projection issues an early warning with a
countdown — that is the feature we consider our main contribution. At
twenty-five seconds it commits to stress, and at forty-eight seconds to anxiety,
which triggers a HIGH alert and offers the breathing exercise. The exercise is a
four-four-four-four box-breathing rhythm, and afterwards the system measures the
actual drop in heart rate — it does not assume the intervention worked, it
checks. At two minutes the state moves to recovery, then calm. Ending the
session produces a report with time in each state, the episodes, and whether
each warning was correct."

---

## Slide 7 — Innovation / Novelty

**Purpose:** why this is not just another dashboard. Pick the five below — they
are the genuinely defensible ones.

- **Personal baseline, not fixed thresholds** — the system calibrates to each
  user before it judges anything
- **Predictive, not reactive** — projects the current trend up to 30 seconds
  ahead and warns before the state changes
- **Movement rejection without an accelerometer** — a heart-rate rise with a
  *flat* skin response is classified as **activity**, not anxiety
- **Two-tier explainable decision** — the ML model is a second opinion that can
  confirm but never overrule the transparent rules; the dashboard shows both
  verdicts
- **Closed-loop intervention** — it does not just alert; it guides breathing and
  then **measures the physiological recovery**
- **Self-auditing reports** — each session is graded on its own evidence quality
  and says so when the data was too poor to trust

**Where the accuracy honesty goes.** Add this as a spoken point, or a sixth
bullet if space allows:

- **We audited our own metric** — found our 95.8% was a leaky split, re-tested
  chronologically (48.5%) and by grouped folds (72.8%), and demoted the model to
  a confirming role rather than shipping the inflated number

**Speaker script (~60 s):** "Four things make this different. First, everything
is relative to your own baseline, so it works across different resting
physiologies. Second, it is predictive — it warns during the rise, not after the
peak. Third, movement rejection: our device has no accelerometer, but a heart
rate that climbs while skin response stays flat is physical activity, not
anxiety, and we classify it as such. Fourth, the loop is closed — the system
intervenes and then measures whether the intervention actually worked. And one
point of rigour: our model reported 95.8% accuracy, but we found that split was
leaky. Tested honestly it is between 48 and 73 percent, so we do not claim it —
the model only confirms the rule engine, never overrules it."

---

## Slide 8 — Future Scope

**Purpose:** show you know exactly what is unfinished. Judges test whether you
know your own limits. Be specific — vague future work reads as no future work.

- **Add an accelerometer** — remove the single biggest source of false positives
  by measuring motion directly instead of inferring it
- **Collect a subject-labelled dataset** and retrain with a
  **subject-independent split**, to replace the current leaky validation with a
  defensible accuracy figure
- **Calibrate GSR to microsiemens** — currently reported in raw 0–1200 sensor
  units, which prevents comparison with published research
- **Miniaturise and add on-board storage**, so the device works away from a
  laptop and syncs later
- **Longitudinal tracking** — trends across sessions, so a user can see change
  over weeks rather than minutes
- **Clinical validation** with supervised trials before any health claim is made

**Speaker script (~40 s):** "The clearest next step is an accelerometer — we
reject motion by inference today, and measuring it directly would remove our
largest error source. Second, a properly labelled multi-subject dataset so we
can report an accuracy figure we can defend. Third, calibrating GSR into
microsiemens so our numbers are comparable with published work. Longer term:
on-board storage so it works untethered, tracking across sessions, and clinical
validation before anyone makes a health claim."

---

## Slide 9 — Thank You / Queries

Keep the template as-is. Optionally add one line:

> Live demo available — [github.com/dangimanjeetsingh/anxiety-state-monito](https://github.com/dangimanjeetsingh/anxiety-state-monito)

Have the dashboard **already running on the laptop, on the projector's second
screen**, before this slide appears. When a judge asks "can we see it?", the
answer should be one click, not one minute of setup.

---

## Screenshot shot-list

Capture these from a running session. Start the app in demo mode
(`python app.py --scenario anxiety`) so you can reach any state on demand.

| # | Shot | Used on | How to get it |
| --- | --- | --- | --- |
| 1 | Full dashboard, **CALM** | Slide 2 | Start a session, wait past calibration |
| 2 | Full dashboard, **ANXIETY** (red) | Slide 6 | `--scenario anxiety`, wait ~100 s after calibration |
| 3 | **Calibrating** state with the progress ring | Slide 6 (small inset) | The first 30 s of any session |
| 4 | **Early warning pill** with countdown | Slide 6 or 7 | During the rise, before the state changes |
| 5 | **Breathing exercise** modal mid-cycle | Slide 6 or 7 | Click the 🫁 button |
| 6 | **Recovery summary** with the measured HR drop | Slide 7 | After a breathing exercise finishes |
| 7 | **Session report** — time in each state, episodes | Slide 6 | End a session |
| 8 | The **device itself**, worn | Slide 1 or 3 | Photograph on a plain background |
| 9 | The **circuit / wiring** | Slide 3 | Photograph or a Fritzing-style diagram |

Crop the browser chrome out of every screenshot. A full-bleed dashboard image
looks like a product; a screenshot with tabs and a URL bar looks like homework.

---

## Live demo runbook

If the panel asks for a demo, this is the two-minute version. **Rehearse it
once.** The single biggest risk is the calibration wait, so start early.

**Before the session begins**

1. Start the app: `python app.py --scenario anxiety`
2. Open `http://127.0.0.1:5000` and press **Start Session** *while the previous
   team is presenting*, so calibration is finished before your turn.

**The two minutes**

| Say this | Show this |
| --- | --- |
| "It learns your own baseline first" | The Calibrated pill with the baseline values |
| "This is live data at one reading per second" | The chart moving |
| "It warns before the state changes" | The early-warning pill and countdown |
| "Now it commits to anxiety — note it went through stress first" | The state card turning red, the ladder |
| "It intervenes, and then measures whether it worked" | Breathing modal → recovery summary |
| "And every run produces this" | End Session → the report |

**Answer for "is this real data?":** "This is our scripted demo generator, which
runs through the identical pipeline — the same code path as the hardware. We use
it because we cannot ethically induce an anxiety episode in a person on demand.
The device is here and connects the same way." Then show the device.

That answer is a credit to you, not an excuse. Say it confidently.

---

## Judge Q&A bank

The questions most likely to come, with answers you can actually defend.

**"How accurate is it?"**
See § The accuracy claim. Lead with the audit, not the number.

**"How do you know it isn't just detecting exercise?"**
"A rise in heart rate with a *flat* skin response is classified as activity, not
anxiety — sympathetic arousal raises both channels, physical effort mainly raises
one. We do not have an accelerometer, so this inference is our motion defence,
and adding one is our first item of future work."

**"What if the sensor slips?"**
"Confidence is scored from data volume, how much survived the plausibility
checks, and how erratic the signal is. Below 0.5 the system downgrades its own
verdict — anxiety becomes stress, stress becomes calm. Poor contact makes the
system quieter, not louder."

**"Why not use deep learning?"**
"Two reasons. Our dataset is small and unlabelled by subject, which is exactly
where deep models overfit — we already found leakage with a Random Forest.
Second, this is a wellbeing tool: it has to explain why it said what it said. A
threshold on HR and GSR relative to your own baseline can be justified to a user;
a neural network's activation cannot."

**"Can this diagnose anxiety disorder?"**
"No, and we state that in the interface. It is an educational wellness
prototype. HR and GSR are affected by movement, temperature, caffeine and sensor
placement. We make no diagnostic claim."

**"Why does it take 30 seconds to start?"**
"It is measuring your resting baseline. Without it we would be comparing you to
a population average, which is exactly the failure mode we set out to avoid. It
also requires the period to be *steady* — if you fidget, it keeps waiting rather
than locking a bad baseline."

**"What happens if Bluetooth disconnects mid-session?"**
"The reader retries continuously, the dashboard shows disconnected, and the
report records the disconnection and counts it against that session's reliability
grade. The report tells you when it should not be trusted."

**"What is your contribution over an existing fitness band?"**
"Three things a band does not do: it predicts the transition before it happens,
it intervenes and then measures whether the intervention worked, and it grades
its own evidence quality so you know when to disbelieve it."

**"Who wrote the code / what did each member do?"**
Agree this answer as a team before you walk in. Have it ready.

---

## Numbers you may quote, and their source

Every figure here is real and traceable to the repository.

| Figure | Value | Where it comes from |
| --- | --- | --- |
| Sampling rate | 1 reading per second | Device firmware, `bt_reader.py` |
| Calibration window | ~30 seconds, steady | `config.py` |
| Analysis window | last 30 seconds | `config.py` |
| Anxiety threshold | HR **+12 bpm** and GSR **+80 units** above baseline | `config.py` |
| Stress threshold | HR **+6 bpm** or GSR **+40 units** | `config.py` |
| Activity rule | HR rising with GSR under **+25** | `config.py` |
| Stabilisation | majority of last **7** verdicts, confirmed **twice** | `config.py` |
| State hold times | **3 s / 3 s / 5 s / 5 s** | `state_machine.py` |
| Forecast horizon | up to **30 seconds** ahead | `config.py` |
| Breathing technique | 4-4-4-4 box breathing, 1–3 minutes | `frontend/js/app.js` |
| Recovery measurement | 60-second observation window | `frontend/js/app.js` |
| ML model | Random Forest, 10 features, binary | `ml/train.py` |
| Accuracy, leaky split | 95.78% — **do not quote alone** | `docs/CHANGELOG.md` |
| Accuracy, chronological | 48.5% | `docs/CHANGELOG.md` |
| Accuracy, grouped 4-fold | 72.8% mean (44.6–88.4%) | `docs/CHANGELOG.md` |

**Never state on a slide:** any diagnostic claim, any clinical accuracy claim,
any comparison to a medical device, or the 95.78% figure without its caveat.

---

## Final checklist

Before the deck is finished:

- [ ] Exactly 9 slides, template order unchanged
- [ ] 20 pt Calibri body text, department name and page numbers on every slide
- [ ] No slide has more than ~6 bullets
- [ ] Hardware part numbers on slide 3 confirmed with the hardware member
- [ ] Every `[CONFIRM]` placeholder replaced
- [ ] Slide 5 is a diagram, not a paragraph
- [ ] Slide 6 has at least one real dashboard screenshot, browser chrome cropped
- [ ] The accuracy figure appears **only** with its caveat, if at all
- [ ] The disclaimer "educational wellness prototype, not a diagnostic device"
      appears somewhere in the deck
- [ ] Laptop tested on the actual projector, dashboard already running
- [ ] Demo rehearsed once end to end, including the calibration wait
- [ ] Every team member can answer "what does your part do" in one sentence

**Where to read more while writing the slides**

| For | Read |
| --- | --- |
| What every file does, in plain English | [CODE_GUIDE.md](CODE_GUIDE.md) |
| Exact algorithms and formulas | [ARCHITECTURE.md](ARCHITECTURE.md) |
| The accuracy audit in full | [CHANGELOG.md](CHANGELOG.md) |
| Settings, thresholds, how to run | [../README.md](../README.md) |
