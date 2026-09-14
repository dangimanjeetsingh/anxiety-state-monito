# The project explained for a non-programmer

This guide explains **every folder and every file** in this project, what each
one does, and how a single heartbeat reading travels from the sensor on a
finger all the way to the word on the screen.

It assumes you cannot read code and do not want to. There is no code in this
document — only descriptions of what each piece is responsible for. If you read
it top to bottom you will be able to explain the whole system to someone else,
including an examiner.

**Contents**

1. [Five words of jargon you need](#1-five-words-of-jargon-you-need)
2. [What the system does, in one page](#2-what-the-system-does-in-one-page)
3. [The journey of a single reading](#3-the-journey-of-a-single-reading)
4. [The folder map](#4-the-folder-map)
5. [The backend, file by file](#5-the-backend-file-by-file)
6. [The frontend, file by file](#6-the-frontend-file-by-file)
7. [The machine-learning folder](#7-the-machine-learning-folder)
8. [The data folder](#8-the-data-folder)
9. [Everything else in the repository](#9-everything-else-in-the-repository)
10. [Two worked examples, end to end](#10-two-worked-examples-end-to-end)
11. [What happens when things go wrong](#11-what-happens-when-things-go-wrong)
12. [The important numbers, and what they mean](#12-the-important-numbers-and-what-they-mean)
13. ["I want to change X" — where to look](#13-i-want-to-change-x--where-to-look)
14. [Glossary](#14-glossary)

---

## 1. Five words of jargon you need

Just five. Everything else in this guide is plain English.

| Word | What it actually means here |
| --- | --- |
| **File** | One document of instructions, ending in `.py` (Python, the backend language), `.js` (JavaScript, runs in the browser), `.html` (the page structure) or `.css` (the page's looks). |
| **Module** | One `.py` file that does one job. This project has 18 of them, each named after its job — `rules.py` holds the rules, `features.py` does the measuring, and so on. |
| **Function** | A named instruction inside a file — "given these numbers, give me back that answer". Think of it as a single recipe in a cookbook. |
| **Class** | A bundle of related functions plus the notes it keeps between calls. `BaselineTracker` is a class: it remembers the resting heart rate it measured, and offers functions that use it. |
| **Thread** | Two things happening at the same time. This app runs the sensor listener on one thread and the web page server on another, so a slow web page never delays a reading. |

One more concept, because it explains the whole architecture:

> **Each file is a station on an assembly line.** A reading enters at one end as
> two raw numbers and leaves at the other end as a word on a screen. Every file
> in `backend/` is one station: it receives something, does exactly one job to
> it, and hands it on. Nothing skips ahead, and no station knows how the others
> work internally. That is why you can understand this project one file at a
> time.

---

## 2. What the system does, in one page

A small wearable device measures two things about a person, once per second:

- **HR — heart rate**, in beats per minute. Anxiety usually raises it.
- **GSR — galvanic skin response** (also called EDA), a measure of how well the
  skin conducts a tiny electrical current. Sweat glands respond to stress before
  you consciously notice it, and sweat conducts electricity, so this number
  rises when someone becomes aroused. It is reported here in **raw sensor units
  from 0 to 1200**, not in calibrated microsiemens.

The device sends those two numbers over Bluetooth to this application, which:

1. **Learns what "normal" is for this particular person** during the first ~30
   seconds — because a resting heart rate of 55 and one of 85 are both perfectly
   healthy, and only the *change from your own normal* means anything.
2. **Watches the last 30 seconds continuously** and works out how far above that
   personal normal the person currently is.
3. **Decides on a state** — CALM, STRESS, ANXIETY or RECOVERY — using two
   independent methods that must agree, then refuses to change its mind too
   quickly.
4. **Warns before it happens** when the trend is heading upward.
5. **Offers a guided breathing exercise** and then measures whether it actually
   worked.
6. **Writes a session report** — how long in each state, what episodes occurred,
   whether the warnings were right, whether the breathing helped.

The whole thing is deliberately conservative. It would rather say STRESS and be
a bit late than shout ANXIETY at someone who just scratched their nose.

---

## 3. The journey of a single reading

This is the most important section of the guide. Everything else is detail.

Imagine the device buzzes once. Here is what happens in the next few
milliseconds, and which file is responsible for each step.

```
       THE DEVICE                            "GSR:640,HR:88"
            │                                (one line of text over Bluetooth)
            ▼
 ┌──────────────────────┐
 │  bt_reader.py        │  Listens to the Bluetooth port. Reads the text,
 │  "the ears"          │  pulls the two numbers out, throws away junk lines
 └──────────┬───────────┘  like "Place finger".
            │  hr = 88, gsr = 640
            ▼
 ┌──────────────────────┐
 │  pipeline.py         │  Is 88 a physically possible heart rate? (40–210)
 │  "the bouncer"       │  Yes → average it with the last 2 readings to remove
 └──────────┬───────────┘  jitter, and add it to a rolling 30-second memory.
            │  smoothed hr = 87.3, and a 30-second window of history
            ▼
 ┌──────────────────────┐
 │  features.py         │  First 30 seconds: quietly measure this person's
 │  "the measurer"      │  resting normal, and predict nothing.
 └──────────┬───────────┘  After that: how far above normal is the 30-second
            │              average? How fast is it climbing? How trustworthy
            │              is this data?
            │  "HR is 18 above your normal, GSR is 140 above, rising, 90% confident"
            ▼
 ┌──────────────────────┐   ┌──────────────────────┐
 │  rules.py            │   │  ml_predictor.py     │  Two independent opinions,
 │  "the doctor's       │   │  "the pattern        │  formed at the same time
 │   rulebook"          │   │   matcher"           │  from the same measurements.
 └──────────┬───────────┘   └──────────┬───────────┘
            │  "ANXIETY"                │  "ANXIETY, 84% sure"
            └────────────┬──────────────┘
                         ▼
              ┌──────────────────────┐
              │  fusion.py           │  Do they agree? If yes, high confidence.
              │  "the referee"       │  If the model disagrees, the rulebook
              └──────────┬───────────┘  wins — the model is only a second opinion.
                         │  "ANXIETY, both agree"
                         ▼
              ┌──────────────────────┐
              │ prediction_smoother  │  Look at the last 7 verdicts. Only accept
              │ .py "the committee"  │  a change if the majority says so, twice
              └──────────┬───────────┘  in a row. Kills flicker.
                         │  "ANXIETY"
                         ▼
              ┌──────────────────────┐
              │  state_machine.py    │  Enforces realistic transitions: you
              │  "the gatekeeper"    │  cannot jump from calm to anxious
              └──────────┬───────────┘  instantly, and you cannot go from
                         │              anxious straight back to calm without
                         │              passing through recovery.
                         │  FINAL STATE: "ANXIETY"
                         ▼
      ┌──────────────────┼──────────────────┬─────────────────────┐
      ▼                  ▼                  ▼                     ▼
┌────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│ pattern_   │   │ alert_       │   │ trend_       │   │ session_recorder │
│ detector   │   │ system       │   │ predictor    │   │ .py              │
│ "what kind │   │ "how loudly  │   │ "what's      │   │ "the scribe" —   │
│ of change  │   │ to say it"   │   │ coming next" │   │ tallies it all   │
│ was that?" │   │              │   │              │   │ for the report   │
└─────┬──────┘   └──────┬───────┘   └──────┬───────┘   └─────────┬────────┘
      └─────────────────┴──────────────────┴─────────────────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │  state_service.py    │  The manager. Runs all of the
                        │  "the conductor"     │  above in order, keeps the one
                        └──────────┬───────────┘  official answer, writes the log.
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │  flask_app.py        │  Publishes that answer to the
                        │  "the receptionist"  │  browser once per second.
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │  frontend/           │  Draws it: the big word, the
                        │  "the face"          │  chart, the breathing exercise.
                        └──────────────────────┘
```

**Two things worth noticing about this diagram.**

First, the decision is made in *stages that each make it harder to raise an
alarm* — a rule must fire, a model must agree, a majority of recent verdicts
must agree, and a timer must expire. That is deliberate. A false "ANXIETY" on a
wellbeing dashboard is worse than a late one.

Second, everything after the state machine is *commentary*: the pattern, the
alert level, the forecast and the report are all descriptions of a decision that
has already been made. If you only remember one path through the code, remember
the vertical spine: **ears → bouncer → measurer → rulebook + model → referee →
committee → gatekeeper**.

---

## 4. The folder map

```
project-code/
├── app.py            ← the starter button: the file you run
├── backend/          ← all the thinking (18 working files + one empty marker)
├── frontend/         ← what you see in the browser (3 files)
├── ml/               ← the trained model and the script that trains it
├── data/             ← what the app writes down while it runs
├── docs/             ← documentation, including this guide
├── requirements.txt  ← the shopping list of software the app needs
└── (loose .txt files)← old scratch notes from development
```

That is the whole project. Four folders that matter, one file you run.

---

## 5. The backend, file by file

The backend is the part with no visuals — the reasoning. Every file lives in
`backend/`. They are listed here in the order a reading passes through them, not
alphabetically, because that order is the one that makes sense.

---

### `app.py` — the starter button

**In the root folder, not in `backend/`.** This is the file you actually run
(`python app.py`). It is short, and it does exactly four things:

1. Turns on logging, so the terminal prints what is happening.
2. Reads the settings (from `config.py`).
3. Reads any switches you typed on the command line — `--mock` to run without
   hardware, `--scenario anxiety` to pick a demo script, `--quiet` to stop
   printing every sensor line.
4. Starts the sensor listener and the web server, then waits.

Think of it as the ignition key. It contains no logic about anxiety at all.

---

### `config.py` — the settings panel

**Every adjustable number in the entire project lives here**, in one file, so
you never have to hunt through the code to change a threshold. Examples of what
it holds:

- which Bluetooth port to use, and how fast to talk to it
- how long calibration should take (30 seconds)
- how far above normal counts as STRESS, and how far counts as ANXIETY
- how many recent verdicts the "committee" looks at (7)
- how often to write to the log file (once per second)

Two useful properties:

- **Nothing is hidden.** If a number matters, it is here with a comment saying
  what it does.
- **Every setting can be overridden without editing the file**, by setting an
  "environment variable" before you start the app. That is how the mock mode,
  the demo scenarios and the server port are switched.

---

### `paths.py` — the address book

Tiny file, one job: work out **where things are on disk**, relative to the
project folder, so the app runs identically on any computer. It answers
questions like "where should the log go?" (`data/logs/`) and "where is the
trained model?" (`ml/model.pkl`), and it creates those folders if they are
missing. Without this, the project would only work on the machine it was written
on.

---

### `bt_reader.py` — the ears (and the demo generator)

This file has **two personalities**.

**Personality 1: the real sensor listener.** It opens the Bluetooth serial port
and listens continuously on its own thread. The device sends plain text like
`GSR:640,HR:88`, once per second. This file:

- pulls the two numbers out of that text, tolerating small format differences
- recognises status messages such as "Place finger" and turns them into a
  warning on the dashboard instead of treating them as data
- silently discards anything it cannot understand, rather than crashing
- notices when the device goes quiet for more than 5 seconds and says so
- reconnects automatically, forever, if the connection drops

**Personality 2: the demonstration generator.** When you run with `--mock`, no
hardware is involved: this file *invents* readings and feeds them into the same
pipeline the real sensor uses. Nothing downstream can tell the difference.

The invented readings are not random. They follow a **script** — a list of
phases with a target heart rate and skin response for each, which the file
smoothly moves between and sprinkles with a little realistic noise:

| Scenario | What it plays |
| --- | --- |
| `demo` | The full arc, about 7 minutes, then repeats: calm → building stress → stress → escalation → anxiety → coming down → recovery → calm → physical activity → calm |
| `anxiety` | Goes to a held anxiety state quickly and stays there |
| `stress`, `calm`, `activity`, `recovery` | One situation each, held |

**Why scripted phases and not a simple wave?** Because of how the measuring
stage works. `features.py` compares the **average of the last 30 seconds** to
your normal. A 5-second spike, however tall, barely moves a 30-second average —
so a short spike can never reach the anxiety threshold, no matter how dramatic
it looks on the chart. Every raised phase in the script is therefore held for
longer than 30 seconds. This is exactly why the earlier version of the demo
could only ever reach STRESS.

---

### `pipeline.py` — the bouncer

Small file, three jobs, applied to every single reading before anyone is allowed
to reason about it:

1. **Reject the impossible.** A heart rate must be between 40 and 210; a skin
   response between 0 and 1200. A reading of 6 bpm is a sensor glitch, not a
   medical emergency, and it is dropped.
2. **Smooth it.** Each reading is averaged with the two before it. This removes
   the tiny second-to-second jitter that every optical sensor produces, without
   noticeably delaying real changes.
3. **Remember the last 30 seconds.** It keeps a rolling window of smoothed
   readings and quietly discards anything older. That window is the raw material
   for every measurement in the next stage.

---

### `features.py` — the measurer (the most important file)

If you only read about one backend file, read about this one. It does two
distinct jobs.

**Job 1: calibration — learning this person's normal.**

For roughly the first 30 seconds of a session, this file collects readings and
makes **no prediction at all**. It is waiting for a stretch of ~30 seconds that
is *steady* — not just long enough, but calm enough (it checks that the numbers
are not swinging around). If the person fidgets, the window slides forward and
keeps waiting rather than locking a bad baseline. Once it finds a steady
stretch, it takes the average heart rate and skin response as **the baseline**
and locks it for the rest of the session.

This is the single design decision that makes the whole project defensible: a
heart rate of 95 means nothing on its own; 95 when *your* resting rate is 68
means a great deal.

**Job 2: turning 30 seconds of numbers into ten measurements.**

Once calibrated, for every new reading it recalculates ten values from the
30-second window. In plain English:

| Measurement | What it means |
| --- | --- |
| mean HR / mean GSR | The average of the last 30 seconds |
| std HR / std GSR | How jumpy the last 30 seconds were |
| HR trend / GSR trend | Are they climbing or falling, and how steeply |
| **delta HR** | **How far the average is above your personal baseline** |
| **delta GSR** | Same, for skin response |
| stress index | The two deltas combined into a single number |
| **confidence** | **How much this data can be trusted, from 0 to 1** |

The last one deserves its own explanation. **Confidence** is scored from three
things: whether the window is actually full of data, how much of that data
survived the plausibility checks, and how wildly the numbers were swinging. Low
confidence usually means poor skin contact or a moving hand. Downstream, a low
confidence score forces the system to *downgrade* its verdict — ANXIETY becomes
STRESS, STRESS becomes CALM. The system distrusts itself when the evidence is
weak.

This file also refuses to produce anything at all if the window has fewer than
10 readings, covers less than 10 seconds, or is more than half rubbish.

---

### `rules.py` — the doctor's rulebook (Tier 1)

The first of the two opinions. It is deliberately simple, completely
transparent, and can be explained to anyone in one sentence per rule:

- **Both** heart rate **and** skin response well above your normal (more than
  +12 bpm and +80 units) → **ANXIETY**.
- **Either one** moderately above (more than +6 bpm or +40 units) →
  **STRESS**.
- Heart rate climbing steeply but skin response *flat* → **ACTIVE** — this is
  someone moving, not someone anxious. Physical effort raises the pulse; it does
  not trigger the sweat response the same way. This is the project's main
  defence against mistaking movement for distress.
- Was elevated, and heart rate is now clearly falling → step down one level,
  so the dashboard follows the person down instead of lagging a minute behind.
- Finally: if confidence is below 0.5, downgrade whatever was decided.

Being rule-based, this tier can always answer the examiner's question "*why* did
it say that?" with a specific number.

---

### `ml_predictor.py` — the pattern matcher (Tier 2)

The second opinion: a **Random Forest**, a trained model that has seen many
examples of calm and anxious readings and learned the patterns that separate
them. (A random forest is a large collection of simple yes/no decision trees
that vote; it is a standard, well-understood method, not a black box neural
network.)

Important honest limitations, all documented in the code:

- The model only knows **two** answers: CALM or ANXIETY. It has no concept of
  stress, activity or recovery.
- It is good at telling "elevated" from "not elevated", but its confidence does
  **not** tell mild elevation apart from severe. Measured on held-out data, it
  reported ANXIETY with essentially the same confidence for a mild rise as for
  a severe one.
- Because of that, by default it is not allowed to escalate the rulebook's
  verdict, only to confirm it.

This file also contains a guard worth knowing about: there is a leftover
`scaler.pkl` file in the `ml/` folder from an earlier version. Applying it to
the current model silently broke the model completely. The file now detects that
mismatch and ignores the stale file, with a warning in the terminal.

---

### `fusion.py` — the referee

Takes the two opinions and produces one. The policy is short:

- Rulebook says ANXIETY **and** the model agrees confidently → **ANXIETY**,
  recorded as "both agree".
- Model says ANXIETY but the rulebook says something milder → **the rulebook
  wins** (unless the escalation setting is deliberately turned on).
- Model says CALM, or its confidence is low → **ignored entirely**; the rulebook
  stands, because the rulebook knows about states the model has never heard of.

The dashboard shows the outcome of this negotiation in small print under the
state — for example "Rules: CALM · ML (2nd opinion): ANXIETY · decided by rules".
Nothing is hidden from the viewer.

---

### `prediction_smoother.py` — the committee

Very short file, one job: **stop the display flickering.** It keeps the last 7
verdicts. The verdict shown is whichever one holds the majority — and even then
it only switches after the new majority has held for two readings in a row.

A single odd reading can therefore never change the display. Roughly 4 or more
consecutive verdicts are needed to move the needle.

---

### `state_machine.py` — the gatekeeper

The final authority on what the dashboard says. It enforces the idea that
physiological states have *shape*: they do not teleport.

The permitted journeys, and how long each requires:

```
   CALM ──3s──► STRESS ──3s──► ANXIETY
     ▲             │               │
     └────3s───────┘               │ 5s (requires heart rate actually falling)
     ▲                             ▼
     └──────────5s───────────  RECOVERY
```

Rules it enforces:

- **You cannot go from CALM to ANXIETY directly** — you must pass through
  STRESS. The one exception is a genuine emergency reading (the combined stress
  index above 12), which is allowed to skip, but still has to hold for 3
  seconds.
- **You cannot go from ANXIETY to CALM directly.** Recovery is a real
  physiological phase, and the dashboard shows it. Leaving anxiety requires the
  heart rate to actually be falling.
- Every transition has a **hold time**: the new condition must persist for the
  stated number of seconds or the timer resets.

One honest consequence, worth knowing before a demo: **RECOVERY is usually
visible for only about 5 seconds.** That is this file's own arithmetic (5
seconds to enter it, and a competing 3-second rule that sends it back to STRESS
if the evidence still looks elevated), not a flaw in the data.

---

### `pattern_detector.py` — what *kind* of change was that?

The state says *where* the person is. This file says *how they got there*, by
comparing the current measurements against the last 60 seconds:

| Pattern | Meaning |
| --- | --- |
| `RAPID_STRESS_SPIKE` | A sharp jump in the last 5–10 seconds — a startle or a sudden trigger |
| `GRADUAL_STRESS_BUILD` | A steady climb over 20–40 seconds — building tension |
| `SLOW_RECOVERY` | Coming down, but slowly |
| `UNSTABLE_SIGNAL` | The numbers are swinging in a way that is not a real trend — usually poor contact or movement |
| `NORMAL` | Nothing notable |

There is a subtlety in here that is a good story to tell: a genuine rapid spike
*also* looks like an unstable signal, because both are "the numbers moved a lot".
The file therefore checks for a structured, directional spike **first**, and only
calls it instability if it cannot find one. Before that fix, every real onset was
being reported as a sensor fault.

---

### `alert_system.py` — how loudly to say it

Turns the state plus the pattern plus the confidence into one of four
loudness levels, which is what the dashboard's colours and prompts key off:

| Level | When |
| --- | --- |
| **HIGH** | ANXIETY, sustained more than 10 seconds, with confidence above 0.6 |
| **MEDIUM** | STRESS sustained more than 20 seconds, **or** a rapid spike detected |
| **LOW** | A gradual build, or a slow recovery |
| **NONE** | Nothing worth saying |

Notice that HIGH requires *both* duration and trustworthy data. A brief blip on
noisy data cannot produce a high alert.

---

### `trend_predictor.py` — the early warning

This is the project's headline feature: **saying something before the state
changes.** It draws a straight line through the current trend and asks "at this
rate, when would the threshold be crossed?"

Safeguards that stop it being a nuisance:

- It says nothing until calibration is complete.
- It says nothing if confidence is below 0.5.
- It only looks 30 seconds ahead — beyond that a straight line is fantasy.
- If the heart rate falls for two readings in a row, the warning is **cleared
  immediately** rather than left to expire.

The dashboard shows it as a countdown pill ("trending toward STRESS, ~18s"). The
session report later scores these forecasts against what actually happened,
which is how you can honestly quote a hit rate.

---

### `session_manager.py` — the session's life story

A session is a deliberate act of measurement, with a beginning and an end. This
small file tracks which of four phases it is in:

```
IDLE ──(you press Start)──► CALIBRATING ──(baseline locks)──► MONITORING ──(you press End)──► ENDED
```

It also invents the session's identity — a filename-safe id like
`20260914-101530-a3f2` — and answers questions the rest of the app asks
constantly, such as "are we recording?" and "how long have we been monitoring?".

Why it matters: **outside a session the app still reads and displays the
sensor**, so you can check the hardware, but it evaluates nothing, records
nothing and writes no report. Nothing is measured by accident.

---

### `session_recorder.py` — the scribe

The largest file in the backend, and conceptually the simplest: for every single
evaluated reading, it **adds one more line to the tally**. At the end it turns
that tally into the session report. It tracks:

- seconds spent in each state, and the episodes (a continuous stretch of stress
  or anxiety, with its start, end and peak)
- every early warning issued, and whether the predicted state actually arrived
- every breathing exercise: when it started, how long it ran, how much the heart
  rate and skin response changed, and whether the person reached calm afterwards
- data-quality evidence: how many readings were rejected, average confidence,
  how much time the signal was unstable, every disconnection
- a **reliability grade** for the session as a whole

That grade is the part to highlight to an examiner. The report does not simply
present its numbers as fact: it first judges whether the session earned the
right to be believed — Was calibration completed? Was enough of the data
usable? Was confidence high enough? A session that fails those tests is labelled
`LIMITED` **and told why**, and short sessions have sections withheld entirely
rather than computed from too little evidence.

It also writes a checkpoint file every 10 seconds, so a session interrupted by a
crash or a power cut can still be recovered and read.

---

### `report_render.py` — the report in other formats

The report is produced as structured data (JSON). This file converts that same
data into a **printable HTML page** and a **spreadsheet-friendly CSV**, so the
report can be opened in a browser or in Excel. It only formats; it never
calculates anything new, so the three formats cannot disagree.

---

### `state_service.py` — the conductor

The file that holds the whole orchestra together. It owns one copy of every
component described above and, for each reading that arrives, runs them in
order, then stores the result as **the single official answer** the rest of the
app reads.

Its other responsibilities:

- **Locking.** The sensor thread and the web server thread both touch the same
  data. This file makes sure only one of them does so at a time, which is what
  prevents the dashboard ever showing a half-updated mixture of two readings.
- **The log file.** It appends one row per second to `data/logs/physio_log.csv`.
- **Checkpoints.** It asks the recorder to save its progress every 10 seconds.
- **Crash recovery.** On startup it looks for checkpoint files from sessions that
  never ended, and turns them into reports marked "interrupted".
- **Session commands.** Start, end, restart calibration, log an exercise.

If you ever want to know "what actually happens per reading", this is the file
that spells it out in order.

---

### `flask_app.py` — the receptionist

Everything the browser can ask for, and nothing more. Flask is the small web
framework that serves the page and answers requests.

| Address | What it gives back |
| --- | --- |
| `/` | The dashboard page itself |
| `/data` | The current snapshot, once |
| `/stream` | A permanently open connection that pushes a fresh snapshot **once per second** — this is what makes the dashboard live without you refreshing |
| `/session/start`, `/session/end` | Begin and finish a session |
| `/session/calibration/restart` | Try calibrating again |
| `/session/intervention`, `/session/exercise` | Record that a breathing exercise started, finished or was abandoned |
| `/sessions` | The list of past sessions |
| `/session/<id>/report`, `.html`, `.csv` | One past session's report in each of the three formats |

The "push once per second" connection (`/stream`) is worth understanding: the
browser does not repeatedly ask "any news?". It opens one connection and the
server writes a new line down it every second. That is why the dashboard updates
smoothly at low cost.

---

### `__init__.py`

An empty file whose only purpose is to tell Python that `backend/` is a package
of modules that belong together. It contains nothing.

---

## 6. The frontend, file by file

Three files, in `frontend/`. Everything the user sees.

### `index.html` — the structure

The skeleton of the page: every element that can ever appear, in order, whether
or not it is currently visible. Roughly top to bottom:

- **Header** — the title, the session chip and timer, Start/End Session,
  Sessions, the Calibrated pill, and the two panel buttons (*How to use* and
  *How it works & Evidence*).
- **Status row** — connection pill, calibration banner (while calibrating), and
  the early-warning pill (after).
- **The state card** — the big word, the caption, the guidance text, and the
  vertical CALM/STRESS/ANXIETY/RECOVERY ladder.
- **Heart rate and GSR cards** — the live numbers, a mini bar chart, and a
  rising/falling badge.
- **The chart** — the last 60 seconds of both signals.
- **Overlays**, all hidden until needed: the breathing modal, the recovery
  summary, the session report, the past-sessions list, the start dialog, and the
  slide-in guide drawer with its three tabs.

The state card is worth one extra note: **all six versions of the guidance text
are written in the page from the start** (one each for calm, stress, anxiety,
recovery, calibrating and idle), and the styling simply reveals the right one.
No code assembles sentences at runtime, so what you read in the file is exactly
what a user can ever see.

### `style.css` — the looks

Everything visual: colours, spacing, sizes, animations, and how the layout
rearranges on a phone. Two ideas do most of the work:

- **One colour per state, defined once.** Each state sets a single colour
  variable, and the state word, the card's glow, the border, the guidance panel
  and the ladder marker all follow it automatically. That is why the whole card
  recolours together and can never end up half green and half red.
- **Sizes that scale with the window** rather than being fixed, so the dashboard
  fits a projector and a phone without a separate design for each.

It also honours the "reduce motion" accessibility setting by switching off the
pulsing and the transitions.

### `app.js` — the behaviour

The browser-side logic. Its jobs:

- Hold the open connection to `/stream` and, once per second, update the state
  word, the numbers, the chart, the trend badges and every banner.
- Run the **breathing exercise**: the 4-4-4-4 rhythm (inhale 4s, hold 4s, exhale
  4s, hold 4s) with an animated circle, then a 60-second observation window,
  then a summary of what actually changed. It tells the backend when the exercise
  starts, ends or is abandoned, so the report can record it.
- Run the session controls, the past-sessions list and the report view.
- Open and close the guide drawer and switch its three tabs.

One design point to note: **`app.js` never decides anything about the person's
state.** It receives a decision and draws it. Every judgement in this project is
made in Python, in the files described above, where it can be logged, tested and
explained. This matters, because it means the picture on the screen and the row
in the log file can never disagree.

---

## 7. The machine-learning folder

`ml/` contains four things.

### `ml/data/training_data.csv`

The training examples: raw heart-rate and skin-response readings, each labelled
calm or anxious.

### `ml/train.py`

The script that turns those examples into a model. The important detail is that
**it does not learn from raw numbers**. It replays the training data through the
*same* smoothing, the *same* baseline calibration and the *same* measuring code
that the live app uses, and learns from the resulting measurements. If the two
differed, the model would be answering a different question at runtime than the
one it was trained on — a classic and invisible failure.

### `ml/model.pkl`

The trained model, saved to disk. (`.pkl` is simply Python's format for saving a
trained object.) The app loads it at startup; if it is missing, the app still
runs perfectly well on the rulebook alone and says so in the terminal.

### `ml/scaler.pkl`

**A leftover that is deliberately ignored.** An earlier version of the training
script rescaled the numbers before learning; the current one does not. Applying
the old rescaling to the current model silently destroyed its accuracy. Rather
than delete the file and leave a trap for anyone restoring it, `ml_predictor.py`
detects the mismatch and refuses to use it, printing a warning. This is a good
example to have ready if you are asked about handling of failure modes.

---

## 8. The data folder

Everything the app writes down.

### `data/logs/physio_log.csv`

One row per second, from the moment the app starts, whether or not a session is
running. Each row records: the time, which session it belongs to and its phase,
the heart rate and skin response, the exact raw text the device sent, **what
each stage decided** (the rulebook's verdict, the model's, the referee's and the
final one), the connection status, and any breathing-exercise event.

Because every stage's verdict is recorded separately, you can open this file
afterwards and see precisely where a decision came from — for example, that the
model said ANXIETY at 10:14:03 but the rulebook overruled it. This is the
project's audit trail.

### `data/sessions/`

One file per session, written when a session ends: the full report as structured
data. Files ending `.partial.json` are checkpoints of a session still running or
one that was interrupted. This folder is created automatically and is excluded
from version control, since it is different on every machine.

---

## 9. Everything else in the repository

| Item | What it is |
| --- | --- |
| `requirements.txt` | The list of external software the project needs (Flask for the web server, pyserial for Bluetooth, scikit-learn for the model, and so on). One command installs everything on the list. |
| `README.md` | The project specification: what it is, how to run it, every setting, and its known limits. |
| `docs/ARCHITECTURE.md` | The same pipeline described here, but written for a programmer, with the exact formulas and data formats. |
| `docs/CHANGELOG.md` | The development journal: what changed, when, why, and what was verified. |
| `docs/TESTING.md` | The manual checklist run before a change is considered done, and how to reproduce each state without hardware. |
| `docs/CODE_GUIDE.md` | This document. |
| `PLAN.md`, `CODEBASE_MEMORY.md` | Working notes kept during development. |
| `.gitignore` | A list of things not to store in version control — temporary files, session files, and other things that are different on every machine. |
| `.claude/launch.json` | A small convenience file that tells the development tooling how to start the app. |
| Loose `.txt` files in the root | Leftover scratch output from development sessions (`train_log.txt`, `diag_out.txt` and similar). They are not used by the running app and can be deleted. |

---

## 10. Two worked examples, end to end

### Example A: a calm person, one minute in

The device sends `GSR:505,HR:71`.

1. **bt_reader** reads the line, extracts 505 and 71.
2. **pipeline** accepts both as plausible, averages 71 with the previous two
   readings to get 70.6, and adds it to the 30-second window.
3. **features**: calibration finished 30 seconds ago and locked a baseline of
   HR 70, GSR 500. The 30-second average is HR 70.4, GSR 502. So delta HR is
   +0.4 and delta GSR is +2. The numbers are barely moving, so confidence is
   0.97.
4. **rules**: +0.4 is below the +6 stress threshold, and +2 is below +40. No rise
   in heart rate without skin response, so not activity. Verdict: **CALM**.
5. **ml_predictor**: also says CALM.
6. **fusion**: model agrees with the rulebook; nothing to negotiate. **CALM**.
7. **smoother**: the last 7 verdicts were all CALM. **CALM**.
8. **state_machine**: already CALM, no transition proposed. **CALM**.
9. **pattern_detector**: nothing changing. `NORMAL`.
10. **alert_system**: `NONE`. **trend_predictor**: nothing projected.
11. **state_service** stores the snapshot, writes the log row, and the recorder
    adds one more second to the "calm" tally.
12. **flask_app** pushes it; the browser shows a green **CALM** with the ladder
    lit at the first step.

### Example B: an anxiety episode, from onset to recovery

Times are from the start of the rise. This is what the `demo` scenario produces,
and it matches what the offline pipeline replay confirmed.

| Time | What the body is doing | What the system does |
| --- | --- | --- |
| 0s | Heart rate begins climbing, skin response with it | Nothing yet — the 30-second average has barely moved |
| ~10s | Both still climbing | `GRADUAL_STRESS_BUILD` detected; the **early warning** pill appears with a countdown |
| ~20s | HR now ~+7, GSR ~+35 above baseline | The rulebook starts saying STRESS; the committee is not convinced yet |
| ~25s | Sustained | The committee agrees; three seconds later the gatekeeper commits to **STRESS**. Alert becomes MEDIUM after 20 seconds of it |
| ~40s | Sharp escalation | `RAPID_STRESS_SPIKE`; the rulebook says ANXIETY; the model agrees |
| ~48s | Both well above baseline (+15 HR, +90 GSR) | The committee flips to ANXIETY, then the gatekeeper holds it for 3 seconds and commits to **ANXIETY**. Alert **HIGH**. The breathing exercise is offered |
| 48s–2m | Held | Recorded as one **episode**, with its peak. The earlier warning is scored as a hit |
| ~2m | Person calms; heart rate starts to fall | The rulebook steps down to STRESS; the gatekeeper sees a falling heart rate and, after 5 seconds, moves to **RECOVERY** |
| ~2m 10s | Still coming down | **CALM** — via recovery, never directly from anxiety |
| End | You press End Session | The report is written: time in each state, one anxiety episode with its duration and peak, the warning marked correct with its lead time, the breathing exercise with the measured heart-rate drop, and a reliability grade |

---

## 11. What happens when things go wrong

A fair question from any examiner is "what if it breaks?" Every case below is
handled deliberately, not by accident.

| Situation | What the system does |
| --- | --- |
| **The sensor is not touching skin properly** | The device sends "Place finger"; `bt_reader` recognises it and the dashboard shows a sensor warning instead of inventing data |
| **Bluetooth drops mid-session** | The reader retries forever with a delay; the dashboard shows disconnected; the report records the disconnection and counts it against the session's reliability grade |
| **The device goes quiet without disconnecting** | After 5 seconds of silence the dashboard says "no data" |
| **The person moves their hand** | Heart rate rises without skin response → the rulebook calls it **ACTIVE**, not anxiety. If the movement makes the signal erratic, confidence falls and the verdict is downgraded, and the pattern is reported as `UNSTABLE_SIGNAL` |
| **The person cannot sit still enough to calibrate** | The calibration window keeps sliding forward looking for a steady stretch rather than locking a bad baseline; the dashboard offers **Restart calibration** |
| **A single wild reading arrives** | Rejected as physically impossible, or absorbed by the smoothing and outvoted by the committee |
| **The trained model is missing or broken** | The app runs on the rulebook alone and says so in the terminal — the model is optional by design |
| **The app crashes mid-session** | The 10-second checkpoint file survives; on the next start it is converted into a report marked "interrupted" |
| **The data was simply too poor to trust** | The report says so explicitly, grades the session `LIMITED`, lists the reasons, and withholds sections it does not have the evidence for |

---

## 12. The important numbers, and what they mean

Everything here is set in `config.py` and can be changed without touching any
logic.

| Number | Value | Plain meaning |
| --- | --- | --- |
| Sample rate | 1 per second | How often the device reports |
| Smoothing window | 3 readings | Each reading is averaged with the previous two |
| Analysis window | 30 seconds | All judgements use the last 30 seconds, not the instant |
| Calibration | ~30 seconds | How long learning your normal takes |
| Anxiety thresholds | +12 bpm **and** +80 GSR | Both must be exceeded |
| Stress thresholds | +6 bpm **or** +40 GSR | Either is enough |
| Activity ceiling | GSR under +25 | A heart-rate rise below this skin response is movement |
| Confidence floor | 0.5 | Below this, the verdict is downgraded |
| Committee size | last 7 verdicts | Majority rules |
| Confirmations | 2 in a row | Before the majority is accepted |
| Hold times | 3s / 3s / 5s / 5s | Calm→stress, stress→anxiety, anxiety→recovery, recovery→calm |
| Emergency skip | stress index above 12 | The only way to reach anxiety without passing through stress |
| High alert | 10 seconds of anxiety | Plus confidence above 0.6 |
| Forecast horizon | 30 seconds | The furthest ahead a warning will look |
| Checkpoint | every 10 seconds | How much of a session a crash can cost |

---

## 13. "I want to change X" — where to look

| I want to… | File | Notes |
| --- | --- | --- |
| Make it more or less sensitive | `backend/config.py` | Lower the thresholds for more sensitivity; expect more false positives |
| Change how long calibration takes | `backend/config.py` | Shorter is faster to demo but learns a less reliable normal |
| Change the demo script or add a scenario | `backend/bt_reader.py` | Keep every raised phase longer than 30 seconds, or it will not register |
| Change the wording shown for each state | `frontend/index.html` | All six versions are written out in the state card |
| Change colours, sizes or spacing | `frontend/css/style.css` | One colour variable per state drives the whole card |
| Change what the report contains | `backend/session_recorder.py` | It computes the report; `report_render.py` only reformats it |
| Change how the state can move | `backend/state_machine.py` | This is where the hold times and permitted transitions live |
| Retrain the model | `ml/train.py` | Run it after changing `ml/data/training_data.csv` |
| Change the Bluetooth port | `backend/config.py`, or set `ANXIETY_COM_PORT` | The port name differs per computer |

---

## 14. Glossary

**Baseline** — your own resting heart rate and skin response, measured at the
start of each session. Everything is judged relative to it.

**Bluetooth serial** — the simple way this device talks to the computer: a
one-way stream of plain text lines, like a very slow typewriter.

**Confidence** — a 0-to-1 score for how trustworthy the current measurements
are. Not a confidence that the person is anxious; a confidence that the *data*
is worth reasoning about.

**CSV** — a plain text table that opens in Excel. Used for the log and one of
the report formats.

**Delta** — the difference between now and your baseline. "Delta HR +12" means
twelve beats per minute above your own normal.

**FSM / finite state machine** — the gatekeeper: a set of allowed moves between
states, with a minimum time for each.

**GSR / EDA** — galvanic skin response: how well your skin conducts a small
current, which rises with stress-related sweat. Reported here in raw units,
0–1200.

**JSON** — a structured text format for data, used for the reports and for
everything the browser receives.

**Mock mode** — running with invented sensor data instead of a device, so every
feature can be demonstrated without hardware.

**Random Forest** — the trained model: many small decision trees that vote.

**Session** — a deliberate, bounded measurement with a start, a calibration, a
monitored period, an end, and a report.

**SSE / server-sent events** — the one-way connection that lets the server push
a fresh reading to the browser every second without the page reloading.

**Stress index** — the two deltas combined into one number, used for the
emergency shortcut and for trend forecasting.

**Threshold** — a line in the sand. Cross it and the verdict changes.

**Window** — the last 30 seconds of readings, which is what every judgement is
actually based on.
