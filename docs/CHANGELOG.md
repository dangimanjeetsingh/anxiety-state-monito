# Change log and engineering journal

The development record: the UI redesign phases, the post-redesign rounds, the
accuracy corrections found in review, and the pre-freeze reliability pass. Each
entry states what changed, why, what was verified, and any deviation left open.

Newest work is at the bottom of each thread rather than the top, so a section
reads in the order it happened.

For the current state of the system, see the [README](../README.md) and
[docs/ARCHITECTURE.md](ARCHITECTURE.md).

---

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

---

## UI round 6 — device guide in the header, wider drawer, rebuilt state panel

Three changes, all driven by how the dashboard reads during a live demo.

- **"How to use the device" moved into the header.** It used to be a `<details>`
  block at the very bottom of the page, below the chart, where nobody scrolled
  to it — and its steps still described the pre-session build. It is now a third
  tab inside the existing guide drawer, opened by a **How to use** button in the
  header next to *How it works & Evidence*. The content was rewritten against
  what the app actually does today: wear → power on (2 beeps) → **Start Session**
  → ~30 s calibration with the progress ring and Calibrated pill → live states,
  early-warning pill and the guided breathing intervention → **End Session** →
  in-app report with JSON/HTML/CSV downloads and the Sessions list. The
  no-accelerometer warning is kept and now explains the ACTIVE rule that partly
  compensates for it. `frontend/js/app.js` generalised its two-tab drawer logic
  to an N-tab list; either header button opens the drawer on its own tab, and
  focus returns to whichever button was used.
- **Drawer width 720px → `min(1180px, max(72vw, 560px))`** (full width below
  700px). At 1440px the panel was using half the screen for content and half for
  backdrop, which squeezed the evidence tables and the pipeline ribbon.
- **State panel rebuilt.** The state word is now the largest thing on the page
  (`clamp(2.1rem, 6.2vh, 3.5rem)`, uppercase) with a correspondingly larger dial;
  the guidance micro-copy moved from a bare hairline-separated column into a
  tinted, state-coloured panel that stretches the full height of its column; and
  the dead space is now an **arousal ladder** — CALM · STRESS · ANXIETY ·
  RECOVERY as a quiet vertical rail in a third column, immediately right of the
  guidance, with the live step's marker filled and haloed and its label in the
  state colour. It reads as the scale the state is being placed on rather than a
  row of buttons bolted under the card. The ladder is pure CSS keyed off the
  `.state-card.state-*` class `app.js` already sets, so there is no new JS and
  nothing extra to keep in sync; it dims during calibration, between sessions,
  and when readings go stale. Below 900px it moves under the guidance, still
  vertical, behind a hairline.

Verified live in mock mode at 1440×900 and 375×812: calibrating → CALM → (forced)
ANXIETY all render with the correct colour on the word, the guidance panel and
the ladder step; all three drawer tabs open, switch and scroll; no console errors
and no horizontal overflow. Fixed one pre-existing bug found on the way:
`.instr-step strong` was unscoped, so every emphasised phrase inside an
instruction paragraph broke onto its own line.

## Accuracy corrections (post-review)

A correctness review of the full inference chain found defects that meant the app was not
reporting what it measured. Each is listed with the evidence that identified it and the fix.

### The ML tier was applying a scaler the model was never trained with

`ml/train.py` fits the RandomForest on raw feature vectors and saves no scaler, but
`MlPredictor` was loading a leftover `ml/scaler.pkl` from an earlier pipeline and z-scoring
every input. Replaying the model's own training data through the live path:

| Inference path | Agreement with labels | ANXIETY recall |
|---|---|---|
| Raw features (as trained) | 91.4% | 80.7% |
| Scaled by the stale file (as deployed) | 64.3% | **0.0%** |

The deployed model returned `CALM` for all 5,302 samples, including all 1,894 labelled
anxiety. `MlPredictor` now applies a scaler only when the estimator carries the
`saarthi_scaled_` marker, and logs a warning when it ignores a stale file.

The two figures in the table above were measured before the model was last retrained. The
current `ml/model.pkl` scores 96.7% agreement and 98.1% ANXIETY recall on the same replay. Both
numbers are *training-data* replays and are not validation figures — see
[Final reliability check](#final-reliability-check-pre-freeze) for what the model is actually
worth on unseen data. `ml/scaler.pkl` is still present on disk and still ignored, with the
warning logged at every boot.

### Feature confidence could never exceed 0.8

`compute_feature_quality_score()` scored sample volume as `num_raw_samples / 60`, but the
sliding window is `sliding_window_seconds` long at ~1 Hz and holds about 30 samples. Confidence
was therefore capped at 0.8 and ran near 0.6, while every downstream gate was written for a
0–1 scale:

- `rules.py` demotes ANXIETY to STRESS and STRESS to CALM below 0.5
- `fusion.py` requires `ml_confidence * feature_confidence >= 0.75`, i.e. the model needed
  0.94 confidence to be heard at all — measured 0 passes in 45 on a textbook anxiety signal
- `alert_system.py` requires confidence above 0.6 for a HIGH alert
- the session report grades a mean below 0.45 as `LIMITED`

The volume term is now measured against a full window (`_OPTIMAL_WINDOW_SAMPLES`). Typical
confidence moved from ~0.62 to ~0.95.

### A real arousal onset was reported as a sensor fault

`PatternDetector` tested `std_hr > 15` before testing for `RAPID_STRESS_SPIKE`. A fast rise
inside a 30 s window *is* high standard deviation — a 70→110 bpm step onset scores 20.0 — so
every genuine spike was labelled `UNSTABLE_SIGNAL` and the spike branch never ran. Across
recorded sessions, 32 of 38 episodes carried `UNSTABLE_SIGNAL` and `RAPID_STRESS_SPIKE` fired
zero times. The spike check now runs before the variance gate: a structured directional change
explains the variance, so only unexplained volatility is reported as unstable.

### Early warnings forecast a threshold the rules do not use

The STRESS rule fires on `delta_hr > 6` **or** `delta_gsr > 40`; the ANXIETY rule needs
**both** `delta_hr > 12` **and** `delta_gsr > 80`. The forecaster compared a single summed
stress index against both, so it under-stated a GSR-driven STRESS that had already crossed and
promised an ANXIETY that an HR-only rise can never reach. It now projects each channel to its
own threshold and combines them the way the rule does — soonest channel for OR, last channel
for AND, and no forecast at all when a channel's trend will never arrive.

### The displayed state lagged recovery by about a minute

Because the rules read a 30 s window mean, both deltas stay above the anxiety thresholds for
roughly a window after the wearer has started to settle, so ANXIETY was asserted through a
clear sustained fall. Falling HR from an elevated state now steps down one level, letting the
state machine route ANXIETY → RECOVERY. Against a scripted 60 s recovery, the reported state
went from 100% ANXIETY to 50% STRESS / 43% ANXIETY / 6% RECOVERY.

Some lag is inherent: the state describes a 30 s trailing mean and cannot lead it. With an
instantaneous return to baseline, ANXIETY persists for about 30 s by construction.

### The ML tier now corroborates rather than overrides

The model is binary (CALM / ANXIETY) while the rules are multi-class. Measured against held-out
segments it reports ANXIETY for mild elevation (HR +8, GSR +50) with the same confidence as for
full arousal (HR +35, GSR +220) — median 0.799 against 0.802. It separates *elevated* from
*calm* well but carries no information about severity, so unmuting it as an override turned a
correctly-reported moderate-stress period into 100% ANXIETY.

The model therefore confirms the rules' ANXIETY (`fusion_source: "both"`) and no longer promotes
STRESS to ANXIETY on its own. Set `ANXIETY_ML_ALLOW_ESCALATION=1` to restore the overriding
behaviour.

### Smaller corrections

- HR readings of 180–210 bpm were accepted by the pipeline and then silently discarded by the
  feature stage's 40–180 clamp, which could suppress prediction entirely during extreme
  tachycardia. The two stages now agree on the plausible range.
- A motion guard in `rules.py` tested `delta_gsr < 25` inside a branch that already required
  `delta_gsr > 80`; it was unsatisfiable and never ran. Removed, with the reasoning recorded.
- Session state-time credited the interval spanning a transition to the *new* state. It is now
  credited to the state actually held during it, so `sum(states.seconds)` matches the monitored
  duration exactly.
- A session interrupted during calibration left no checkpoint to recover; checkpoints are now
  written during `CALIBRATING` as well.
- A breathing exercise could be started during `CALIBRATING`, where there is no baseline to
  measure against and a different time origin, producing an all-null record. It now returns
  `409 not_monitoring`.

### Known operational limit

Two backend instances pointed at the same `data/logs/physio_log.csv` will interleave rows;
there is no lock file. Run one instance per log.

### Additional configuration variable

| Variable | Default | Purpose |
|---|---|---|
| `ANXIETY_ML_ALLOW_ESCALATION` | `false` | Allow the ML tier to raise the rules' verdict from STRESS to ANXIETY |

---

## Final reliability check (pre-freeze)

A last verification pass over the model, the rule/ML/fusion chain, and the full runtime, run in
mock mode (`ANXIETY_USE_MOCK_SERIAL=1`) against a live server. Scope was deliberately narrow: no
new features, no redesign, and no change to anything that was not a demonstrated defect. One bug
was found and fixed; every other finding is recorded here without a code change.

### Model provenance and feature parity

| Check | Result |
|---|---|
| Feature count and order, training vs inference | Identical — one definition, `FeatureVector.as_list()` |
| Preprocessing, training vs inference | Identical — `train.py` drives the real `DataPipeline` + `BaselineTracker` + `compute_features` |
| Is `ml/model.pkl` the current `train.py` output? | Yes — 100.00% prediction agreement on all 5,335 rows after retraining |
| Is a stale scaler being applied? | No — refused, with a boot warning |

Feature parity is guaranteed by construction rather than by convention: there is exactly one
place where the ten features are named and ordered, and both paths call it. `model.n_features_in_`
is 10.

### The reported accuracy is measured on a leaky split

`ml/train.py` splits with `train_test_split(..., shuffle=True)` — a random *row* split over a
30 s sliding window sampled at 1 Hz. Adjacent rows share about 29 of their 30 underlying samples,
so nearly every test row has a near-duplicate in the training set. The headline number reproduces
exactly, but it measures memorisation of overlapping windows, not generalisation:

| Split protocol | Accuracy | ANXIETY recall |
|---|---|---|
| Random row split (the reported figure) | **95.78%** | 97.6% |
| Chronological 80/20 | **48.5%** | — |
| Grouped by contiguous label block, 4-fold | **72.8%** mean (44.6–88.4%) | 0.45 / 0.75 / 1.00 |

`ml/data/training_data.csv` carries no subject or session column, so a subject-independent split
is not possible with this dataset at all. The split was left unchanged: altering it would
invalidate the shipped model, which is a retraining decision rather than a bug fix.

**The 95.7% quoted in the dashboard's Research & Evidence panel should be read as a leaky
upper bound.** The panel already warns that the labels were generated by the same delta logic the
rule engine uses; it does not yet disclose the split problem.

### Deterministic behaviour of rules + ML + fusion

Six scenarios were driven through the real chain — pipeline → baseline → features → rules → ML →
fusion → smoother → FSM:

| Scenario | Rules | ML | Fused (source) | Final |
|---|---|---|---|---|
| Flat baseline | CALM | ANXIETY @ 0.63 | CALM (rules) | **CALM** |
| Moderate stress, HR +8 / GSR +50 | STRESS | ANXIETY @ 0.83 | STRESS (rules) | **STRESS** |
| Strong arousal, HR +30 / GSR +220 | ANXIETY | ANXIETY @ 0.81 | ANXIETY (both) | **ANXIETY** |
| HR-only rise, +25 | STRESS | ANXIETY @ 0.83 | STRESS (rules) | **STRESS** |
| GSR-only rise, +200 | STRESS | ANXIETY @ 0.77 | STRESS (rules) | **STRESS** |
| Recovery ramp-down | — | — | — | ANXIETY → **RECOVERY** → STRESS → **CALM** |

The model reports ANXIETY above the 0.75 fuse threshold in all three moderate cases and in none of
them does the fused state escalate. The corroboration gate described above is doing exactly the
job it was added for. No logic defect was found in `rules.py` or `fusion.py`.

The flat-baseline row is the one worth remembering: on a perfectly still 70 bpm / 500 GSR signal
the model still reports ANXIETY, at 0.63. It is safe only because fusion cannot act on it.

### Bug fixed: calibration could never complete above 1 s sample spacing

`BaselineTracker.update_with_sample()` pruned every sample older than the calibration window
*before* measuring the buffer's span. The span therefore settled at `n · dt` for the largest `n`
with `n · dt <= calib_s` — always strictly inside the window, and below the `0.95 * calib_s` lock
check as soon as the inter-sample spacing passed 1.0 s. A 1 Hz Bluetooth link always jitters above
1.0 s.

Measured on a perfectly calm synthetic stream, before the fix:

| Spacing | 10 s window | 30 s window |
|---|---|---|
| 0.98 s | locks (span 9.80) | locks (span 29.40) |
| 1.00 s | locks (span 10.00) | locks (span 29.00) |
| 1.005 s | **never locks** (span 9.04) | locks (span 29.14) |
| 1.01 s | **never locks** (span 9.09) | locks (span 29.29) |
| 1.05 s | **never locks** (span 9.45) | locks (span 29.40) |

Live confirmation: a session with `ANXIETY_BASELINE_CALIBRATION_S=10` sat at
`progress: 0.909, stalled: true` for 240 s and never calibrated. The default 30 s window was
surviving on margin alone — 29.29 s clears the 28.5 s bar — so the defect was invisible in normal
use and fatal in the documented fast-development path.

The prune now keeps the one sample that still makes the buffer span the full window, so the span
is always at least `calib_s`. After the fix calibration locks at every spacing from 0.5 s to
1.05 s for both window lengths, and the live session calibrated in 10.1 s. All six scenarios above
were re-run and are unchanged.

### End-to-end regression after the fix

Verified against a running server in mock mode:

| Surface | Result |
|---|---|
| Calibration | Locks at 10.1 s, `stable: true`, personalised baseline recorded |
| Live HR/GSR | Streaming and plotted; dashboard loads with zero console errors |
| Final states | CALM → STRESS → RECOVERY committed with correct hold durations |
| Prediction | 3 warnings issued, 3 confirmed, lead times 5.1 s and 8.1 s |
| Breathing / interventions | Start and stop accepted, indexed, recovery metrics computed |
| Session start / end | `201` on start, clean end, `.partial.json` promoted to final JSON |
| Report and downloads | JSON, `report.html` `200`, `report.csv` `200`, `/sessions` lists 33, malformed id `404` |
| SSE | Continuous 1 Hz frames for the whole run, no stalls or drops |
| CSV logging | v2 header intact, per-phase rows correct |

### Standing limitations confirmed by this pass

These are design consequences, not defects, and none were changed:

- The binary model is not usable on its own. Do not set `ANXIETY_ML_ALLOW_ESCALATION=1`.
- Calibration locks on the first *stable* window, which is not necessarily a *resting* one. A
  session begun mid-arousal calibrated at HR 104 / GSR 716 and then under-reported every delta for
  the rest of the run. Start sessions at rest.
- Reports withhold sections below 60 s and below 3 min of monitored time, and name what is missing
  in `unavailable`. This is intended.
- `ml/scaler.pkl` remains on disk, ignored, with a warning at every boot.
- Rules can still emit `ACTIVE`, which the FSM treats as a no-op; this can briefly delay a
  transition. Harmless, and unchanged.

### Freeze status

The runtime is safe to freeze with the calibration fix in place. The only source change from this
pass is nine lines in `backend/features.py`.

The accuracy claim is not safe to freeze as written: the 95.7% figure in the UI reflects a leaky
validation protocol, and honest performance on unseen data is roughly 73%, falling to about 45% on
an unseen episode.

---

## System walkthrough panel (exhibition explainer)

A frontend-only addition for judges and live demos: a visual, plain-language explanation of what
the system actually does, openable in a few seconds mid-conversation. No sensing, ML, rule, fusion
or backend behaviour was added or changed — the panel is static markup that describes the existing
pipeline.

### It extends the evidence drawer rather than replacing it

The existing `Method & evidence` drawer is heavily cited and was worth keeping intact, so the
drawer now hosts **two tabs** and the original panel became the second one, unchanged:

| Element | Before | After |
|---|---|---|
| Header button | `Research & Evidence` | `How it works & Evidence` (same `#guideToggle`) |
| Tab 1 | — | **System walkthrough** — new, opens by default |
| Tab 2 | the whole drawer | **Research & evidence** — the original content, unedited |

Open, close, Escape, backdrop click and focus return are the original handlers and are untouched.
The drawer always reopens on the walkthrough: at an exhibition the next question starts from
"how does this work", not from wherever the panel was last left.

### Structure

A six-stop pipeline ribbon (Sense → Calibrate → Clean → Decide → Stabilise → Act & log) carries the
20-second read, followed by eleven numbered cards on a connected spine. Every card has the same
four parts, so a reader's eye lands in the same place each time:

> **what happens** · **Why** it exists · the **Key decision** involved · the **Output** it produces

The eleven cards are: sensor input, personal calibration, signal processing, feature extraction,
rule-based detection, ML model, rule + ML fusion, smoothing & state machine, predictive early
warning, guided breathing & recovery, and session lifecycle & report.

Four cards carry a diagram instead of a paragraph, because the mechanism is faster to see than to
read:

- **Feature extraction** — the ten feature chips, with ΔHR, ΔGSR and stress index highlighted as
  the three that drive decisions.
- **Rule-based detection** — three colour-coded threshold rows reusing the existing state tags.
- **Fusion** — two before/after rows that show the gate's entire point: *Rules ANXIETY + ML ANXIETY
  → corroborated*, against *Rules STRESS + ML ANXIETY → **not escalated***.
- **State machine** — the state chain with each hold time printed under its arrow (3 s / 3 s /
  5 s / 5 s).

Every figure in the panel is taken from the implementation and was verified during the pre-freeze
reliability pass: the 15 bpm / 50 unit calibration stability gate, the 40–210 bpm plausibility
clamp, `ΔHR + 0.05 × ΔGSR`, `probability × confidence ≥ 0.75`, the 7-reading majority vote, the
30 s forecast cap, the 60 s recovery window, and the Insufficient / Limited / Good grading tiers.

### Limitations & future work

The panel closes with its own bordered section stating the build's real limitations — the ~30 s
trailing-window latency, the absence of an accelerometer, the binary model, the leaky validation
protocol (with the ~73% grouped and ~45% unseen-episode figures named outright), calibration
inheriting the wearer's condition at lock time, raw GSR units, and the single-dataset training set.

Future work is visually separated — dashed border, `PROPOSED` badge, and the explicit line
*"none of the following is implemented in the system being demonstrated"* — so a proposal can never
be mistaken for a feature during a demo. The medical disclaimer is repeated at the foot of the tab;
the panel makes no diagnostic, treatment or clinical-accuracy claim anywhere.

### Files touched

| File | Change |
|---|---|
| `frontend/index.html` | Tab bar + the walkthrough panel; existing drawer body wrapped as the second tabpanel, content unedited |
| `frontend/css/style.css` | Appended `.guide-tab*` and `.hiw-*` rules, reusing the existing design tokens |
| `frontend/js/app.js` | `setGuideTab()` plus tablist arrow-key handling; `setGuideOpen()` resets to the walkthrough |

The only rule that touches existing styling makes `.guide-drawer` a flex column so the tab bar can
size itself, replacing a fixed `calc(100dvh - 85px)` body height that would otherwise overflow.
Nothing outside the drawer is affected, and no backend file was modified.

### Verification

The full UI regression checklist was re-run in mock mode at 1280 px and 1024 px, with a live
session driven start to finish: calibration → monitoring → prediction banner → breathing modal →
session end → report. Both drawer tabs switch in both directions with correct ARIA state and scroll
reset, Escape closes and returns focus to the toggle, there is no horizontal scroll at either
width, and the browser console stayed **completely empty** throughout. The monitoring dashboard
itself renders exactly as before.
