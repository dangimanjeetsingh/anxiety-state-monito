// ── DOM refs ────────────────────────────────────────────────────────────────
const HR_EL         = document.getElementById("hrVal");
const GSR_EL        = document.getElementById("gsrVal");
const HR_MINI_BAR   = document.getElementById("hrMiniBar");
const GSR_MINI_BAR  = document.getElementById("gsrMiniBar");
const HR_TREND      = document.getElementById("hrTrend");
const GSR_TREND     = document.getElementById("gsrTrend");
const METRIC_HISTORY_LEN = 8;
let hrHistory = [];
let gsrHistory = [];
const STATE_EL      = document.getElementById("stateVal");
const META_EL       = document.getElementById("metaVal");
const STATE_CARD    = document.getElementById("stateCard");
const STATE_RING_PROGRESS = document.getElementById("stateRingProgressFill");
const STATE_CAL_CAPTION   = document.getElementById("stateCalibratingPct");
const STATE_RING_CIRC = 2 * Math.PI * 46;
const CONN_TEXT     = document.getElementById("connText");
const CONN_DOT      = document.getElementById("connDot");
const BASELINE_INFO = document.getElementById("baselineInfo");
const WINDOW_INFO   = document.getElementById("windowInfo");
const SW_BANNER     = document.getElementById("sensorWarning");
const SW_TEXT       = document.getElementById("sensorWarningText");
const CAL_BANNER    = document.getElementById("calibrationBanner");
const CAL_TITLE     = document.getElementById("calibrationTitle");
const CAL_MESSAGE   = document.getElementById("calibrationMessage");
const CAL_STATUS    = document.getElementById("calibrationStatus");

// Phase 4 refs
const STATUS_STRIP     = document.getElementById("statusStrip");
const CALIBRATED_PILL  = document.getElementById("calibratedPill");
const CALIBRATED_DETAIL= document.getElementById("calibratedDetail");
const GUIDE_TOGGLE  = document.getElementById("guideToggle");
const GUIDE_DRAWER  = document.getElementById("interpretationDrawer");
const GUIDE_BACKDROP = document.getElementById("guideBackdrop");
const GUIDE_CLOSE   = document.getElementById("guideClose");

// Feature 1 refs
const PRED_BANNER       = document.getElementById("predictionBanner");
const PRED_TITLE        = document.getElementById("predictionTitle");
const PRED_DETAIL       = document.getElementById("predictionDetail");
const PRED_COUNTDOWN    = document.getElementById("predictionCountdown");

// Feature 2 refs
const BP_PROMPT         = document.getElementById("breathingPrompt");
const BP_START_BTN      = document.getElementById("bpStartBtn");
const BP_DISMISS_BTN    = document.getElementById("bpDismissBtn");
const MANUAL_BREATHE_BTN= document.getElementById("manualBreatheBtn");
const BM_BACKDROP       = document.getElementById("breathingBackdrop");
const BM_MODAL          = document.getElementById("breathingModal");
const BM_CLOSE_BTN      = document.getElementById("breatheCloseBtn");
const BM_CONFIG_SEC     = document.getElementById("breatheConfigSection");
const BM_RUNNING_SEC    = document.getElementById("breatheRunningSection");
const BM_RECOVERY_SEC   = document.getElementById("breatheRecoverySection");
const BM_START_RUN_BTN  = document.getElementById("breatheStartRunBtn");
const BM_STOP_BTN       = document.getElementById("breatheStopBtn");
const BREATHE_CIRCLE    = document.getElementById("breatheCircle");
const BREATHE_INSTR     = document.getElementById("breatheInstruction");
const BREATHE_STEP_TIMER= document.getElementById("breatheStepTimer");
const BREATHE_PHASE_LBL = document.getElementById("breathePhaseLabel");
const BREATHE_CYCLE_LBL = document.getElementById("breatheCycleCount");
const BREATHE_TIME_REMAIN = document.getElementById("breatheTimeRemain");
const BREATHE_LIVE_HR   = document.getElementById("breatheLiveHr");
const RECOVERY_REMAIN_CD= document.getElementById("recoveryRemainCountdown");

// Recovery Summary refs
const RECOVERY_CARD     = document.getElementById("recoveryCard");
const RC_CLOSE_BTN      = document.getElementById("rcCloseBtn");
const RC_HR_CHANGE      = document.getElementById("rcHrChange");
const RC_HR_DETAIL      = document.getElementById("rcHrDetail");
const RC_STATE_CHANGE   = document.getElementById("rcStateChange");
const RC_STATE_DETAIL   = document.getElementById("rcStateDetail");
const RC_DURATION_VAL   = document.getElementById("rcDurationVal");


// ── Feature: Session lifecycle ────────────────────────────────────
const SESSION_PRIMARY_BTN   = document.getElementById("sessionPrimaryBtn");
const SESSION_CHIP          = document.getElementById("sessionChip");
const SESSION_CHIP_LABEL    = document.getElementById("sessionChipLabel");
const SESSION_CHIP_TIME     = document.getElementById("sessionChipTime");
const SESSION_START_BACKDROP= document.getElementById("sessionStartBackdrop");
const SESSION_START_MODAL   = document.getElementById("sessionStartModal");
const SESSION_START_CLOSE   = document.getElementById("sessionStartCloseBtn");
const SESSION_START_CONFIRM = document.getElementById("sessionStartConfirmBtn");
const SESSION_LABEL_INPUT   = document.getElementById("sessionLabelInput");
const CAL_RESTART_BTN       = document.getElementById("calibrationRestartBtn");
const SESSIONS_LIST_BTN     = document.getElementById("sessionsListBtn");

// ── Chart ────────────────────────────────────────────────────────────────────
const MAX_PTS = 60;
let chart;
let recoveryChart;

// Appearance only: the two signal colours below are the same values the HR and
// GSR cards are tinted with in style.css, so a card and its trace read as one
// signal. Data, labels, dataset order and the state markers are unchanged.
const CHART_HR_COLOR  = "#22D3EE";
const CHART_GSR_COLOR = "#E879F9";
const CHART_GRID       = "rgba(244,244,247,0.06)";
const CHART_TICK       = "rgba(139,139,152,0.9)";
const CHART_TICK_FONT  = { family: "'JetBrains Mono', Consolas, monospace", size: 10 };

// A vertical fade under each trace. Built against the canvas so it follows the
// plot area on resize; falls back to a flat tint before the area is measured.
function chartAreaGradient(context, hex) {
  const chartObj = context.chart;
  const area = chartObj.chartArea;
  if (!area) return hexToRgba(hex, 0.1);
  const g = chartObj.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  g.addColorStop(0, hexToRgba(hex, 0.34));
  g.addColorStop(0.55, hexToRgba(hex, 0.1));
  g.addColorStop(1, hexToRgba(hex, 0));
  return g;
}

function hexToRgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
}

// Soft bloom around the traces — purely decorative, drawn by shadowing the
// line stroke and cleared again so nothing else on the canvas inherits it.
const lineGlowPlugin = {
  id: "lineGlow",
  beforeDatasetDraw: function (chartObj, args) {
    const c = chartObj.ctx;
    c.save();
    c.shadowColor = args.meta.dataset.borderColor;
    c.shadowBlur = 14;
    c.shadowOffsetY = 2;
  },
  afterDatasetDraw: function (chartObj) {
    chartObj.ctx.restore();
  },
};

function initChart() {
  const ctx = document.getElementById("liveChart");
  if (!ctx) return;
  // Highlight the newest sample only, so the eye lands on "now".
  const headPoint = function (size) {
    return function (context) {
      return context.dataIndex === context.dataset.data.length - 1 ? size : 0;
    };
  };
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "HR (bpm)",
          data: [],
          borderColor: CHART_HR_COLOR,
          backgroundColor: function (c) { return chartAreaGradient(c, CHART_HR_COLOR); },
          tension: 0.38,
          borderWidth: 2.4,
          fill: true,
          pointRadius: headPoint(3.6),
          pointHoverRadius: 5,
          pointBackgroundColor: CHART_HR_COLOR,
          pointBorderColor: "#0B0B0F",
          pointBorderWidth: 2,
        },
        {
          label: "GSR / 4",
          data: [],
          borderColor: CHART_GSR_COLOR,
          backgroundColor: function (c) { return chartAreaGradient(c, CHART_GSR_COLOR); },
          tension: 0.38,
          borderWidth: 2.4,
          fill: true,
          pointRadius: headPoint(3.6),
          pointHoverRadius: 5,
          pointBackgroundColor: CHART_GSR_COLOR,
          pointBorderColor: "#0B0B0F",
          pointBorderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      layout: { padding: { top: 16, right: 6, bottom: 0, left: 0 } },
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          border: { display: false },
          // Vertical rules add noise to a time series; the state markers are
          // the only vertical lines worth drawing here.
          grid: { display: false },
          ticks: { color: CHART_TICK, font: CHART_TICK_FONT, maxTicksLimit: 7, maxRotation: 0, padding: 6 },
        },
        y: {
          border: { display: false },
          grid: { color: CHART_GRID, drawTicks: false },
          ticks: { color: CHART_TICK, font: CHART_TICK_FONT, maxTicksLimit: 6, padding: 8 },
        },
      },
      plugins: {
        legend: {
          align: "end",
          labels: {
            color: "rgba(244,244,247,0.75)",
            font: { family: "'Sora', system-ui, sans-serif", size: 11, weight: "600" },
            usePointStyle: true,
            pointStyle: "circle",
            boxWidth: 7,
            boxHeight: 7,
            padding: 18,
          },
        },
        tooltip: {
          backgroundColor: "rgba(11,11,15,0.95)",
          borderColor: "rgba(244,244,247,0.14)",
          borderWidth: 1,
          titleColor: "rgba(139,139,152,0.95)",
          titleFont: { family: "'Sora', system-ui, sans-serif", size: 10, weight: "600" },
          bodyColor: "#F4F4F7",
          bodyFont: { family: "'JetBrains Mono', Consolas, monospace", size: 12 },
          cornerRadius: 8,
          padding: 10,
          displayColors: true,
          usePointStyle: true,
        },
        annotation: { annotations: {} },
      },
    },
    plugins: [lineGlowPlugin],
  });
}

// ── Chart state-transition markers (Phase 5) ───────────────────────────────
// Draws a dashed vertical line + colored label pill at each FSM state change,
// capped to the points still visible in the chart's rolling MAX_PTS window.
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const STATE_MARKER_COLORS = {
  CALM: "--calm",
  STRESS: "--stress",
  ANXIETY: "--anxiety",
  RECOVERY: "--recovery",
};

let lastChartState = null;
let stateMarkers = []; // { id, label } — label must match an entry in chart.data.labels
let markerSeq = 0;

function addStateMarker(label, state) {
  const tokenName = STATE_MARKER_COLORS[state];
  if (!chart || !tokenName) return;
  const color = cssVar(tokenName);
  if (!color) return;

  const id = "stateMarker" + (markerSeq++);
  chart.options.plugins.annotation.annotations[id] = {
    type: "line",
    scaleID: "x",
    value: label,
    borderColor: color,
    borderWidth: 1.25,
    borderDash: [3, 5],
    label: {
      display: true,
      content: state,
      position: "start",
      backgroundColor: color,
      color: cssVar("--bg-base") || "#0B0B0F",
      font: { family: "'Sora', system-ui, sans-serif", size: 9, weight: "700" },
      padding: { top: 3, bottom: 3, left: 7, right: 7 },
      borderRadius: 999,
      yAdjust: -6,
    },
  };
  stateMarkers.push({ id: id, label: label });
}

function pruneStateMarkers(visibleLabels) {
  if (!chart) return;
  const annotations = chart.options.plugins.annotation.annotations;
  const visible = new Set(visibleLabels);
  stateMarkers = stateMarkers.filter(function (m) {
    if (visible.has(m.label)) return true;
    delete annotations[m.id];
    return false;
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function stateClass(s) {
  s = (s || "").toUpperCase();
  return { CALM: "state-calm", STRESS: "state-stress", ANXIETY: "state-anxiety", RECOVERY: "state-recovery", ACTIVE: "state-active" }[s] || "";
}

// Phase 9: nudge the state-card's continuous pulse rate with current HR
// (higher HR = slightly faster). Purely cosmetic — sets a CSS variable only.
function updatePulseRate(hr) {
  if (hr == null) return;
  var clamped = Math.max(50, Math.min(140, hr));
  // Appearance only: --hr-beat is the live beat-to-beat interval, so the heart
  // icon on the HR card beats at the rate actually being measured.
  document.documentElement.style.setProperty("--hr-beat", (60 / clamped).toFixed(3) + "s");
  if (!STATE_CARD) return;
  var duration = 4.2 - ((clamped - 50) / 90) * 2.4; // ~4.2s at 50bpm down to ~1.8s at 140bpm
  STATE_CARD.style.setProperty("--pulse-duration", duration.toFixed(2) + "s");
}

function clearReadings() {
  if (HR_EL)  HR_EL.textContent  = "—";
  if (GSR_EL) GSR_EL.textContent = "—";
  if (STATE_EL) STATE_EL.textContent = "—";
  if (STATE_CARD) STATE_CARD.classList.remove("state-calm", "state-stress", "state-anxiety", "state-recovery", "state-active");
  if (META_EL) META_EL.textContent = "";
  hrHistory = [];
  gsrHistory = [];
  if (HR_TREND) HR_TREND.classList.remove("is-rising", "is-falling");
  if (GSR_TREND) GSR_TREND.classList.remove("is-rising", "is-falling");
}

function setConn(conn, detail) {
  if (!CONN_DOT || !CONN_TEXT) return;
  CONN_DOT.classList.remove("ok", "warn", "bad");
  const c = (conn || "").toLowerCase();
  if (c === "connected" || c === "mock") {
    CONN_DOT.classList.add("ok");
    CONN_TEXT.textContent = c === "mock" ? "Mock serial (synthetic test mode)" : "Bluetooth connected (HC-05)";
  } else if (c === "connecting") {
    CONN_DOT.classList.add("warn");
    CONN_TEXT.textContent = "Connecting to HC-05…";
  } else if (c === "no_data") {
    CONN_DOT.classList.add("warn");
    CONN_TEXT.textContent = "⚠ No sensor data" + (detail ? " · " + detail : "");
  } else {
    CONN_DOT.classList.add("bad");
    CONN_TEXT.textContent = "Bluetooth disconnected" + (detail ? ": " + detail : "");
  }
}

function setSensorWarning(warning) {
  if (!SW_BANNER || !SW_TEXT) return;
  if (warning) {
    SW_TEXT.textContent = warning;
    SW_BANNER.classList.remove("sw-danger");
    SW_BANNER.style.display = "flex";
  } else {
    SW_BANNER.style.display = "none";
  }
}

// ── Round 5: live mini-bar sparkline + trend badge for HR/GSR cards ───────────
function pushHistory(arr, value) {
  arr.push(value);
  if (arr.length > METRIC_HISTORY_LEN) arr.shift();
}

function updateMiniBar(el, history) {
  if (!el) return;
  const bars = el.children;
  const min = Math.min.apply(null, history);
  const max = Math.max.apply(null, history);
  const range = (max - min) || 1;
  for (var i = 0; i < bars.length; i++) {
    var histIdx = history.length - bars.length + i;
    var v = histIdx >= 0 ? history[histIdx] : history[0];
    var pct = 15 + ((v - min) / range) * 75;
    bars[i].style.height = pct.toFixed(0) + "%";
  }
}

function updateTrend(el, history, threshold) {
  if (!el) return;
  var dir = "steady";
  if (history.length >= 4) {
    var recent = history[history.length - 1];
    var past = history[Math.max(0, history.length - 6)];
    var diff = recent - past;
    if (diff > threshold) dir = "rising";
    else if (diff < -threshold) dir = "falling";
  }
  el.classList.remove("is-rising", "is-falling");
  if (dir !== "steady") el.classList.add("is-" + dir);
  var arrowEl = el.querySelector(".metric-trend-arrow");
  var labelEl = el.querySelector(".metric-trend-label");
  var arrow = dir === "rising" ? "↑" : dir === "falling" ? "↓" : "→";
  var label = dir === "rising" ? "Rising" : dir === "falling" ? "Falling" : "Steady";
  if (arrowEl) arrowEl.textContent = arrow;
  if (labelEl) labelEl.textContent = label;
}

// ── Calibration Status ────────────────────────────────────────────────────────
function setCalibrationStatus(d) {
  if (!CAL_BANNER || !CAL_TITLE || !CAL_MESSAGE || !CAL_STATUS) return;

  // NOTE(plan): outside an active session there is no calibration to report,
  // so the banner explains the session state instead of the baseline state.
  if (!(d.session && d.session.recording === true)) {
    CAL_BANNER.classList.remove("is-ready");
    CAL_BANNER.classList.add("is-waiting");
    CAL_TITLE.textContent = "No monitoring session running";
    CAL_MESSAGE.textContent =
      "Live sensor values are shown for a hardware check. Start a session to measure a personal baseline.";
    CAL_STATUS.textContent = "Idle";
    if (STATUS_STRIP) {
      STATUS_STRIP.style.display = "none";
      CAL_BANNER.style.display = "flex";
    }
    // The calibrated pill describes a live baseline; there is none between sessions.
    if (CALIBRATED_PILL) CALIBRATED_PILL.style.display = "none";
    if (CAL_RESTART_BTN) CAL_RESTART_BTN.hidden = true;
    // A breathing exercise is only meaningful against a running session.
    if (MANUAL_BREATHE_BTN) {
      MANUAL_BREATHE_BTN.disabled = true;
      MANUAL_BREATHE_BTN.title = "Start a session to log a breathing exercise";
    }
    return;
  }

  const conn = (d.connection || "").toLowerCase();
  const connected = conn === "connected" || conn === "mock";
  const hasReading = d.hr != null && d.gsr != null;
  const calibrated = d.calibrated === true;
  const isMock = conn === "mock";
  const cal = (d.session && d.session.calibration) || null;
  if (MANUAL_BREATHE_BTN) {
    MANUAL_BREATHE_BTN.disabled = false;
    MANUAL_BREATHE_BTN.title = "";
  }

  // Only offer a restart when the baseline is genuinely failing to settle.
  if (CAL_RESTART_BTN) CAL_RESTART_BTN.hidden = !(cal && cal.stalled);

  CAL_BANNER.classList.toggle("is-ready", calibrated);
  CAL_BANNER.classList.toggle("is-waiting", !connected || !hasReading);

  if (!connected) {
    CAL_TITLE.textContent = "Waiting for sensor connection";
    CAL_MESSAGE.textContent = "Connect the device to begin your personal baseline reading.";
    CAL_STATUS.textContent = "Waiting";
  } else if (!hasReading) {
    CAL_TITLE.textContent = "Waiting for valid sensor readings";
    CAL_MESSAGE.textContent = "Keep the sensors in contact with your skin to start calibration.";
    CAL_STATUS.textContent = "Preparing";
  } else if (cal && cal.paused) {
    CAL_TITLE.textContent = "Calibration paused — sensor not sending data";
    CAL_MESSAGE.textContent = "Check the sensor contact and the Bluetooth link. "
      + "Calibration will resume automatically; nothing measured so far is lost.";
    CAL_STATUS.textContent = "Paused";
  } else if (cal && cal.stalled) {
    CAL_TITLE.textContent = "Still looking for a steady baseline";
    CAL_MESSAGE.textContent = "Signal variation is too high to lock a baseline. "
      + "Rest your hand flat, stop talking, and stay still for about 30 seconds.";
    CAL_STATUS.textContent = "Hold still";
  } else if (!calibrated) {
    // Quote the configured window rather than a hardcoded 30s, so the copy
    // stays true when ANXIETY_BASELINE_CALIBRATION_S is changed.
    var targetS = cal && cal.target_s ? Math.round(cal.target_s) : 30;
    CAL_TITLE.textContent = isMock
      ? "Mock baseline calibration (~" + targetS + "s)"
      : "Baseline calibration in progress";
    CAL_MESSAGE.textContent = isMock
      ? "Mock data generator active. Calibrating baseline over an initial " + targetS
        + " seconds. Predictions will start automatically when ready."
      : "Please sit calmly, keep your hand still, and breathe normally. Your personal baseline is being measured; predictions will start when it is ready.";
    CAL_STATUS.textContent = "Calibrating";
  } else {
    CAL_TITLE.textContent = "Baseline complete";
    CAL_MESSAGE.textContent = isMock
      ? "Synthetic baseline complete. Live mock predictions and trend warnings are now active."
      : "Your personal baseline is ready. Live state predictions are now active.";
    CAL_STATUS.textContent = "Prediction active";
  }

  // Phase 4: once calibrated, swap the full-width banner for the compact
  // status strip so it stops permanently occupying space.
  if (STATUS_STRIP) {
    STATUS_STRIP.style.display = calibrated ? "flex" : "none";
    CAL_BANNER.style.display = calibrated ? "none" : "flex";
  }
  // Calibrated pill now lives in the header (moved out of #statusStrip), so
  // its visibility is no longer implied by the strip's — toggle it directly.
  if (CALIBRATED_PILL) {
    CALIBRATED_PILL.style.display = calibrated ? "flex" : "none";
  }
  if (CALIBRATED_DETAIL) {
    CALIBRATED_DETAIL.textContent = calibrated && d.baseline_hr != null && d.baseline_gsr != null
      ? "Personal baseline locked in — HR " + Math.round(d.baseline_hr) + " · GSR " + Math.round(d.baseline_gsr) + "."
      : "";
  }
}

if (CALIBRATED_PILL && CALIBRATED_DETAIL) {
  CALIBRATED_PILL.addEventListener("click", () => {
    const expanded = CALIBRATED_PILL.getAttribute("aria-expanded") === "true";
    CALIBRATED_PILL.setAttribute("aria-expanded", String(!expanded));
    CALIBRATED_DETAIL.hidden = expanded;
  });
}

// ── Shared: elevated state detection (FSM + ML fusion + alerts) ───────────────
function isMlAnxietyAdopted(d) {
  // Raw ml_state alone is NOT used. Fusion only adopts ML when effective
  // confidence >= ANXIETY_ML_CONFIDENCE (see backend/fusion.py). Both checks
  // must pass: the fused label is ANXIETY AND fusion_source shows ML contributed.
  return (
    d.fused_state === "ANXIETY" &&
    (d.fusion_source === "ml" || d.fusion_source === "both")
  );
}

function isElevatedForBreathing(d) {
  if (!d || d.calibrated !== true) return false;
  return d.state === "ANXIETY" || d.alert === "HIGH" || isMlAnxietyAdopted(d);
}

// ── Feature 1: Predictive Early Warning ───────────────────────────────────────
// Phase 4: this pill lives inside #statusStrip alongside the "Calibrated" pill.
// It never disappears once calibrated — when no prediction is active it falls
// back to a neutral "next reading" message instead of leaving an empty gap,
// but the countdown badge only ever shows a real countdown (see task 5).
const PRED_ICON = PRED_BANNER ? PRED_BANNER.querySelector(".pred-icon") : null;

function updatePredictionBanner(d) {
  if (!PRED_BANNER || !PRED_TITLE || !PRED_DETAIL || !PRED_COUNTDOWN) return;

  if (d.calibrated !== true) {
    // Pre-calibration: #statusStrip itself is hidden by setCalibrationStatus(),
    // so this is just a safe default.
    PRED_BANNER.style.display = "none";
    return;
  }

  const pred = d.prediction;
  PRED_BANNER.style.display = "flex";

  if (pred && pred.active === true && pred.seconds_to_transition != null) {
    const sec = Math.max(1, Math.round(pred.seconds_to_transition));
    const target = pred.predicted_state || "STRESS";
    PRED_BANNER.classList.remove("is-idle");
    if (PRED_ICON) PRED_ICON.textContent = "⚡";
    PRED_TITLE.textContent = "Trending toward " + target + " in ~" + sec + "s";
    PRED_DETAIL.textContent = pred.basis
      ? "Early forecast basis: " + pred.basis + " (linear projection capped at 30s)"
      : "Linear trend projection based on physiological slope indicators.";
    PRED_COUNTDOWN.textContent = "~" + sec + "s";
    PRED_COUNTDOWN.style.display = "";
  } else {
    PRED_BANNER.classList.add("is-idle");
    if (PRED_ICON) PRED_ICON.textContent = "⏱";
    PRED_TITLE.textContent = "Next reading in ~1s";
    PRED_DETAIL.textContent = "Collecting and analysing…";
    PRED_COUNTDOWN.style.display = "none";
  }
}

// ── Feature 2: Breathing Exercise & Recovery Tracking ─────────────────────────
let bpDismissedUntil = 0;
let exerciseDurationSec = 60;
let exerciseRunning = false;
let exerciseTimer = null;
let exerciseStartTime = 0;
let exerciseCycleCount = 0;
let exerciseBoxStep = 0;
let exerciseStepRemain = 4;

let recoveryActive = false;
let recoveryTimer = null;
let recoveryRemainSec = 60;
let exerciseBuffer = [];
let exerciseStartHr = null;
let exerciseStartState = null;

document.querySelectorAll(".btn-duration").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".btn-duration").forEach(b => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    exerciseDurationSec = parseInt(btn.getAttribute("data-duration"), 10) || 60;
  });
});

function openBreathingModal() {
  if (!BM_MODAL || !BM_BACKDROP) return;
  BM_MODAL.hidden = false;
  BM_BACKDROP.hidden = false;
  document.body.classList.add("drawer-open");

  if (!exerciseRunning && !recoveryActive) {
    if (BM_CONFIG_SEC) BM_CONFIG_SEC.style.display = "block";
    if (BM_RUNNING_SEC) BM_RUNNING_SEC.style.display = "none";
    if (BM_RECOVERY_SEC) BM_RECOVERY_SEC.style.display = "none";
  }
}

function closeBreathingModal() {
  if (exerciseRunning || recoveryActive) {
    if (!confirm("Stop the exercise in progress?")) return;
    stopExercise(false);
  }
  if (!BM_MODAL || !BM_BACKDROP) return;
  BM_MODAL.hidden = true;
  BM_BACKDROP.hidden = true;
  document.body.classList.remove("drawer-open");
}

if (BM_CLOSE_BTN) BM_CLOSE_BTN.addEventListener("click", closeBreathingModal);
if (BM_BACKDROP) BM_BACKDROP.addEventListener("click", closeBreathingModal);
if (MANUAL_BREATHE_BTN) MANUAL_BREATHE_BTN.addEventListener("click", openBreathingModal);

if (BP_START_BTN) {
  BP_START_BTN.addEventListener("click", () => {
    if (BP_PROMPT) BP_PROMPT.style.display = "none";
    openBreathingModal();
  });
}

if (BP_DISMISS_BTN) {
  BP_DISMISS_BTN.addEventListener("click", () => {
    if (BP_PROMPT) BP_PROMPT.style.display = "none";
    bpDismissedUntil = Date.now() + 120000;
  });
}

// The backend owns the durable intervention record; the animation, phase timer
// and cycle counter stay here. A stop with nothing running is a no-op server-side,
// so the duplicate stop on a natural finish is safe.
function logExerciseBackend(event) {
  fetch("/session/intervention", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event: event,
      technique: "box_4_4_4_4",
      planned_duration_s: exerciseDurationSec,
      cycles_completed: exerciseCycleCount,
    }),
  }).catch(e => console.debug("Intervention log error:", e));
}

function startExercise() {
  exerciseRunning = true;
  recoveryActive = false;
  exerciseStartTime = Date.now();
  exerciseCycleCount = 0;
  exerciseBoxStep = 0;
  exerciseStepRemain = 4;
  exerciseBuffer = [];

  if (lastData && lastData.hr != null) {
    exerciseStartHr = lastData.hr;
    exerciseStartState = lastData.state || "ANXIETY";
  } else {
    exerciseStartHr = null;
    exerciseStartState = "ANXIETY";
  }

  logExerciseBackend("start");

  if (BM_CONFIG_SEC) BM_CONFIG_SEC.style.display = "none";
  if (BM_RUNNING_SEC) BM_RUNNING_SEC.style.display = "block";
  if (BM_RECOVERY_SEC) BM_RECOVERY_SEC.style.display = "none";

  updateBoxPhaseUI();
  if (exerciseTimer) clearInterval(exerciseTimer);
  exerciseTimer = setInterval(runExerciseTick, 1000);
}

if (BM_START_RUN_BTN) BM_START_RUN_BTN.addEventListener("click", startExercise);
if (BM_STOP_BTN) BM_STOP_BTN.addEventListener("click", () => stopExercise(true));

function updateBoxPhaseUI() {
  if (!BREATHE_CIRCLE || !BREATHE_INSTR || !BREATHE_STEP_TIMER || !BREATHE_PHASE_LBL) return;
  BREATHE_STEP_TIMER.textContent = exerciseStepRemain;

  BREATHE_CIRCLE.classList.remove("expand", "hold", "contract", "hold-empty");
  if (exerciseBoxStep === 0) {
    BREATHE_INSTR.textContent = "Inhale";
    BREATHE_PHASE_LBL.textContent = "Inhale";
    BREATHE_CIRCLE.classList.add("expand");
  } else if (exerciseBoxStep === 1) {
    BREATHE_INSTR.textContent = "Hold";
    BREATHE_PHASE_LBL.textContent = "Hold (Full)";
    BREATHE_CIRCLE.classList.add("hold");
  } else if (exerciseBoxStep === 2) {
    BREATHE_INSTR.textContent = "Exhale";
    BREATHE_PHASE_LBL.textContent = "Exhale";
    BREATHE_CIRCLE.classList.add("contract");
  } else {
    BREATHE_INSTR.textContent = "Hold";
    BREATHE_PHASE_LBL.textContent = "Hold (Empty)";
    BREATHE_CIRCLE.classList.add("hold-empty");
  }
}

function runExerciseTick() {
  const elapsedSec = Math.floor((Date.now() - exerciseStartTime) / 1000);
  const remainSec = Math.max(0, exerciseDurationSec - elapsedSec);

  const mins = Math.floor(remainSec / 60);
  const secs = remainSec % 60;
  if (BREATHE_TIME_REMAIN) {
    BREATHE_TIME_REMAIN.textContent = String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
  }

  exerciseStepRemain--;
  if (exerciseStepRemain <= 0) {
    exerciseBoxStep = (exerciseBoxStep + 1) % 4;
    exerciseStepRemain = 4;
    if (exerciseBoxStep === 0) {
      exerciseCycleCount++;
      if (BREATHE_CYCLE_LBL) BREATHE_CYCLE_LBL.textContent = exerciseCycleCount;
    }
  }
  updateBoxPhaseUI();

  if (remainSec <= 0) {
    finishExerciseToRecovery();
  }
}

function finishExerciseToRecovery() {
  if (exerciseTimer) clearInterval(exerciseTimer);
  exerciseRunning = false;
  recoveryActive = true;
  recoveryRemainSec = 60;
  logExerciseBackend("stop");

  if (BM_RUNNING_SEC) BM_RUNNING_SEC.style.display = "none";
  if (BM_RECOVERY_SEC) BM_RECOVERY_SEC.style.display = "block";
  if (RECOVERY_REMAIN_CD) RECOVERY_REMAIN_CD.textContent = "60s";

  if (recoveryTimer) clearInterval(recoveryTimer);
  recoveryTimer = setInterval(runRecoveryTick, 1000);
}

function runRecoveryTick() {
  recoveryRemainSec--;
  if (RECOVERY_REMAIN_CD) RECOVERY_REMAIN_CD.textContent = recoveryRemainSec + "s";

  if (recoveryRemainSec <= 0) {
    clearInterval(recoveryTimer);
    recoveryActive = false;
    if (BM_MODAL && BM_BACKDROP) {
      BM_MODAL.hidden = true;
      BM_BACKDROP.hidden = true;
      document.body.classList.remove("drawer-open");
    }
    showRecoverySummary();
  }
}

function stopExercise(proceedToRecovery) {
  if (exerciseTimer) clearInterval(exerciseTimer);
  if (recoveryTimer) clearInterval(recoveryTimer);
  exerciseRunning = false;
  recoveryActive = false;
  logExerciseBackend("stop");

  if (proceedToRecovery && exerciseBuffer.length > 5) {
    finishExerciseToRecovery();
  } else {
    if (BM_MODAL && BM_BACKDROP) {
      BM_MODAL.hidden = true;
      BM_BACKDROP.hidden = true;
      document.body.classList.remove("drawer-open");
    }
  }
}

function showRecoverySummary() {
  if (!RECOVERY_CARD) return;
  if (!exerciseBuffer || exerciseBuffer.length === 0) return;

  const firstPt = exerciseBuffer[0];
  const lastPt = exerciseBuffer[exerciseBuffer.length - 1];

  const startHr = exerciseStartHr != null ? Math.round(exerciseStartHr) : Math.round(firstPt.hr);
  const endHr = Math.round(lastPt.hr);
  const deltaHr = endHr - startHr;
  const pctChange = startHr > 0 ? ((deltaHr / startHr) * 100).toFixed(1) : 0;

  if (RC_HR_CHANGE) {
    const sign = deltaHr > 0 ? "+" : "";
    RC_HR_CHANGE.textContent = startHr + " → " + endHr + " bpm (" + sign + deltaHr + ", " + sign + pctChange + "%)";
  }

  if (RC_STATE_CHANGE) {
    const startSt = exerciseStartState || firstPt.state || "ANXIETY";
    const endSt = lastPt.state || "CALM";
    RC_STATE_CHANGE.textContent = startSt + " → " + endSt;
  }

  if (RC_DURATION_VAL) {
    const totalSec = Math.round(lastPt.relTime);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    RC_DURATION_VAL.textContent = (m > 0 ? m + "m " : "") + s + "s tracked";
  }

  renderRecoveryChart();
  RECOVERY_CARD.style.display = "block";
  RECOVERY_CARD.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderRecoveryChart() {
  const ctx = document.getElementById("recoveryChart");
  if (!ctx) return;
  if (recoveryChart) recoveryChart.destroy();

  const labels = exerciseBuffer.map(pt => pt.relTime + "s");
  const hrData = exerciseBuffer.map(pt => pt.hr);

  recoveryChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Heart rate (bpm)",
          data: hrData,
          borderColor: "#4ADE80",
          backgroundColor: function (c) { return chartAreaGradient(c, "#4ADE80"); },
          tension: 0.38,
          pointRadius: 0,
          borderWidth: 2.2,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 10 } },
      scales: {
        x: { border: { display: false }, ticks: { color: CHART_TICK, font: CHART_TICK_FONT, maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } },
        y: { border: { display: false }, grid: { color: CHART_GRID, drawTicks: false }, ticks: { color: CHART_TICK, font: CHART_TICK_FONT, maxTicksLimit: 5, padding: 6 } },
      },
      plugins: {
        legend: {
          align: "end",
          labels: {
            color: "rgba(244,244,247,0.75)",
            font: { family: "'Sora', system-ui, sans-serif", size: 11, weight: "600" },
            usePointStyle: true,
            pointStyle: "circle",
            boxWidth: 7,
            boxHeight: 7,
            padding: 14,
          },
        },
      },
    },
  });
}

if (RC_CLOSE_BTN) {
  RC_CLOSE_BTN.addEventListener("click", () => {
    if (RECOVERY_CARD) RECOVERY_CARD.style.display = "none";
  });
}

// ── Method & Evidence Drawer ──────────────────────────────────────────────────
function setGuideOpen(open) {
  if (!GUIDE_TOGGLE || !GUIDE_DRAWER || !GUIDE_BACKDROP) return;
  GUIDE_DRAWER.hidden = !open;
  GUIDE_BACKDROP.hidden = !open;
  GUIDE_TOGGLE.setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("drawer-open", open);
  if (open && GUIDE_CLOSE) GUIDE_CLOSE.focus();
  if (!open) GUIDE_TOGGLE.focus();
}

if (GUIDE_TOGGLE && GUIDE_DRAWER && GUIDE_BACKDROP) {
  GUIDE_TOGGLE.addEventListener("click", () => setGuideOpen(GUIDE_DRAWER.hidden));
  GUIDE_CLOSE?.addEventListener("click", () => setGuideOpen(false));
  GUIDE_BACKDROP.addEventListener("click", () => setGuideOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !GUIDE_DRAWER.hidden) setGuideOpen(false);
  });
}

let lastData = null;

function render(d) {
  lastData = d;
  updateSessionControls(d);
  const recording = !!(d.session && d.session.recording === true);
  const age = d.server_time ? ((Date.now()/1000 - d.server_time).toFixed(1) + "s old") : "?";
  setCalibrationStatus(d);
  updatePredictionBanner(d);

  // If no sensor data is arriving, blank the value boxes and bail early
  const conn = (d.connection || "").toLowerCase();
  if (conn === "no_data" || conn === "disconnected") {
    clearReadings();
    setConn(d.connection, d.connection_detail);
    setSensorWarning(d.sensor_warning || null);
    return;
  }
  console.log("[" + new Date().toLocaleTimeString() + "] HR=" + d.hr + " GSR=" + d.gsr + " state=" + d.state + " data=" + age);

  if (HR_EL)  HR_EL.textContent  = d.hr  != null ? Math.round(d.hr)  : "—";
  if (GSR_EL) GSR_EL.textContent = d.gsr != null ? Math.round(d.gsr) : "—";
  updatePulseRate(d.hr);

  if (d.hr != null) {
    pushHistory(hrHistory, d.hr);
    updateMiniBar(HR_MINI_BAR, hrHistory);
    updateTrend(HR_TREND, hrHistory, 2.5);
  }
  if (d.gsr != null) {
    pushHistory(gsrHistory, d.gsr);
    updateMiniBar(GSR_MINI_BAR, gsrHistory);
    updateTrend(GSR_TREND, gsrHistory, 15);
  }

  const calibrating = recording && !d.calibrated && (conn === "connected" || conn === "mock");
  if (STATE_EL) {
    STATE_EL.textContent = calibrating ? "CALIBRATING" : (d.state || "—");
    STATE_EL.classList.toggle("state--compact", calibrating);
  }
  if (STATE_CARD) {
    STATE_CARD.classList.remove("state-calm","state-stress","state-anxiety","state-recovery","state-active","state-calibrating");
    var cls = calibrating ? "state-calibrating" : stateClass(d.state);
    if (cls) STATE_CARD.classList.add(cls);
  }
  if (STATE_RING_PROGRESS) {
    // Progress is the real baseline-buffer span reported by the server, not the
    // 30-second prediction window, so the ring cannot sit full while calibrating.
    var cal = (d.session && d.session.calibration) || null;
    var calProgress = (calibrating && cal) ? (cal.progress || 0) : 0;
    STATE_RING_PROGRESS.style.strokeDashoffset = String(STATE_RING_CIRC * (1 - calProgress));
    if (STATE_CAL_CAPTION) {
      if (calibrating && cal && cal.method === "fixed") {
        STATE_CAL_CAPTION.textContent = "Using configured baseline";
      } else if (calibrating) {
        STATE_CAL_CAPTION.textContent =
          "Establishing baseline · " + Math.round(calProgress * 100) + "%";
      } else {
        STATE_CAL_CAPTION.textContent = "Establishing baseline";
      }
    }
  }

  if (META_EL)
    META_EL.textContent = calibrating
      ? "Sit calmly — prediction starts after calibration"
      : "Rules: " + (d.rule_state||"—") + " · ML: " + (d.ml_state||"—") + " · " + (d.fusion_source||"—");

  // Outside an active session the readings are a sensor check only: no state,
  // no prediction strip, no breathing prompt.
  if (!recording) {
    if (STATE_EL) { STATE_EL.textContent = "IDLE"; STATE_EL.classList.add("state--compact"); }
    if (META_EL) META_EL.textContent = "No session running — press Start Session to begin";
    if (BP_PROMPT) BP_PROMPT.style.display = "none";
    if (PRED_BANNER) PRED_BANNER.style.display = "none";
    // No state class: the per-state captions and microcopy describe a reading
    // that does not exist outside a session, so none of them should show.
    if (STATE_CARD) {
      STATE_CARD.classList.remove("state-calm","state-stress","state-anxiety","state-recovery","state-active","state-calibrating");
    }
  }

  setConn(d.connection, d.connection_detail);
  setSensorWarning(d.sensor_warning || null);

  if (BASELINE_INFO && !recording)
    BASELINE_INFO.textContent = "No baseline — start a session to measure one";
  else if (BASELINE_INFO)
    BASELINE_INFO.textContent = d.calibrated && d.baseline_hr != null && d.baseline_gsr != null
      ? "Baseline HR " + Math.round(d.baseline_hr) + " · GSR " + Math.round(d.baseline_gsr)
      : "Baseline calibration in progress — sit calmly";
  if (WINDOW_INFO)
    WINDOW_INFO.textContent = d.window_samples != null
      ? "Window: " + d.window_samples + " samples · calibrated: " + d.calibrated
      : "";

  if (chart && d.hr != null && d.gsr != null) {
    var t = new Date().toLocaleTimeString();

    if (d.state && d.state !== lastChartState) {
      if (lastChartState !== null) {
        addStateMarker(t, d.state);
      }
      lastChartState = d.state;
    }

    chart.data.labels.push(t);
    chart.data.datasets[0].data.push(d.hr);
    chart.data.datasets[1].data.push(d.gsr / 4);
    if (chart.data.labels.length > MAX_PTS) {
      chart.data.labels.shift();
      chart.data.datasets[0].data.shift();
      chart.data.datasets[1].data.shift();
    }
    pruneStateMarkers(chart.data.labels);
    chart.update("none");
  }

  if (BP_PROMPT && recording) {
    const notSuppressed = Date.now() > bpDismissedUntil;
    if (isElevatedForBreathing(d) && notSuppressed && !exerciseRunning && !recoveryActive && (!BM_MODAL || BM_MODAL.hidden)) {
      BP_PROMPT.style.display = "flex";
    } else {
      BP_PROMPT.style.display = "none";
    }
  }

  if ((exerciseRunning || recoveryActive) && d.hr != null) {
    const relSec = Math.round((Date.now() - exerciseStartTime) / 1000);
    exerciseBuffer.push({
      relTime: relSec,
      hr: d.hr,
      gsr: d.gsr,
      state: d.state,
      isRecovery: recoveryActive,
    });
    if (BREATHE_LIVE_HR) {
      BREATHE_LIVE_HR.textContent = Math.round(d.hr) + " bpm";
    }
  }
}

// ── Feature: Session lifecycle — controls, dialog, phase gating ──────────────
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
  if (SESSIONS_LIST_BTN) SESSIONS_LIST_BTN.hidden = false;
  document.body.classList.toggle("session-idle", sess.phase === "IDLE");
  document.body.classList.toggle("session-ended", sess.phase === "ENDED");

  // A newly started session takes over the live view. A report opened from the
  // Sessions list stays reachable: it is an immutable file addressed by id.
  if (sess.recording === true && typeof closeReportPanel === "function"
      && document.body.classList.contains("report-open")) {
    closeReportPanel();
  }
}

function openSessionStartModal() {
  if (!SESSION_START_MODAL) return;
  SESSION_START_MODAL.hidden = false;
  if (SESSION_START_BACKDROP) SESSION_START_BACKDROP.hidden = false;
  if (SESSION_LABEL_INPUT) { SESSION_LABEL_INPUT.value = ""; SESSION_LABEL_INPUT.focus(); }
}

function closeSessionStartModal() {
  if (SESSION_START_MODAL) SESSION_START_MODAL.hidden = true;
  if (SESSION_START_BACKDROP) SESSION_START_BACKDROP.hidden = true;
}

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

if (SESSION_START_CONFIRM) {
  SESSION_START_CONFIRM.addEventListener("click", function () {
    var label = SESSION_LABEL_INPUT ? SESSION_LABEL_INPUT.value : "";
    SESSION_START_CONFIRM.disabled = true;
    fetch("/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: label }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (res.ok) closeSessionStartModal();
        else alert("Could not start a session: " + (res.body.error || "unknown error"));
      })
      .catch(function (e) { console.error("start session:", e); })
      .then(function () { SESSION_START_CONFIRM.disabled = false; });
  });
}

if (CAL_RESTART_BTN) {
  CAL_RESTART_BTN.addEventListener("click", function () {
    CAL_RESTART_BTN.disabled = true;
    fetch("/session/calibration/restart", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j.error) console.warn("restart calibration:", j.error); })
      .catch(function (e) { console.error("restart calibration:", e); })
      .then(function () {
        CAL_RESTART_BTN.disabled = false;
        CAL_RESTART_BTN.hidden = true;
      });
  });
}

if (SESSION_START_CLOSE) SESSION_START_CLOSE.addEventListener("click", closeSessionStartModal);
if (SESSION_START_BACKDROP) SESSION_START_BACKDROP.addEventListener("click", closeSessionStartModal);

// ── Feature: Session report panel ────────────────────────────────────────────
// The report is a pure projection of the report JSON. A value the backend could
// not compute is rendered as "not available — <reason>", never as 0 or a blank.
const RP_PANEL       = document.getElementById("reportPanel");
const RP_LABEL       = document.getElementById("rpLabel");
const RP_META        = document.getElementById("rpMeta");
const RP_STATUS      = document.getElementById("rpStatusBanner");
const RP_RELIABILITY = document.getElementById("rpReliability");
const RP_NARRATIVE   = document.getElementById("rpNarrative");
const RP_STATS       = document.getElementById("rpStats");
const RP_TIMELINE    = document.getElementById("rpTimeline");
const RP_TL_LEGEND   = document.getElementById("rpTimelineLegend");
const RP_EPISODES    = document.getElementById("rpEpisodes");
const RP_WARNINGS    = document.getElementById("rpWarnings");
const RP_INTERV      = document.getElementById("rpInterventions");
const RP_PROVENANCE  = document.getElementById("rpProvenance");
const RP_DOWNLOADS   = document.getElementById("rpDownloads");
const RP_DISCLAIMER  = document.getElementById("rpDisclaimer");
const RP_CLOSE_BTN   = document.getElementById("rpCloseBtn");
const RP_NEW_BTN     = document.getElementById("rpNewSessionBtn");
const SESSIONS_DRAWER  = document.getElementById("sessionsDrawer");
const SESSIONS_BACKDROP= document.getElementById("sessionsBackdrop");
const SESSIONS_LIST    = document.getElementById("sessionsList");
const SESSIONS_CLOSE   = document.getElementById("sessionsCloseBtn");

let openReportId = null;

function rpText(value, fallback) {
  if (value === null || value === undefined || value === "") return fallback || "not available";
  return String(value);
}

function rpNum(value, digits, suffix) {
  if (value === null || value === undefined) return null;
  var n = Number(value);
  if (isNaN(n)) return null;
  return n.toFixed(digits === undefined ? 0 : digits) + (suffix || "");
}

function rpDuration(seconds) {
  if (seconds === null || seconds === undefined) return null;
  var total = Math.max(0, Math.round(seconds));
  if (total < 60) return total + " s";
  return Math.floor(total / 60) + " min " + String(total % 60).padStart(2, "0") + " s";
}

function rpReason(rep, key, fallback) {
  var un = rep.unavailable || {};
  return un[key] || fallback || "not recorded for this session";
}

// One stat tile. `value` of null renders the reason instead of a number.
function rpStat(label, value, reason, desc) {
  var missing = (value === null || value === undefined);
  var div = document.createElement("div");
  div.className = "rc-stat" + (missing ? " rc-stat--missing" : "");
  var l = document.createElement("span");
  l.className = "rc-stat-label";
  l.textContent = label;
  var v = document.createElement("span");
  v.className = "rc-stat-val";
  v.textContent = missing ? "not available" : value;
  div.appendChild(l);
  div.appendChild(v);
  if (missing || desc) {
    var d = document.createElement("span");
    d.className = "rc-stat-desc";
    d.textContent = missing ? (reason || "not recorded for this session") : desc;
    div.appendChild(d);
  }
  return div;
}

function rpClear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); }

function rpMissingSection(el, reason) {
  rpClear(el);
  var p = document.createElement("p");
  p.className = "rp-missing";
  p.textContent = "not available — " + reason;
  el.appendChild(p);
}

function renderReport(rep) {
  if (!rep || !RP_PANEL) return;
  openReportId = (rep.identity && rep.identity.id) || null;
  var identity = rep.identity || {};
  var quality = rep.quality || {};
  var baseline = rep.baseline || {};
  var grade = quality.reliability || "UNKNOWN";
  var provisional = grade === "LIMITED";

  RP_PANEL.classList.toggle("is-provisional", provisional);

  if (RP_LABEL) RP_LABEL.textContent = identity.label || "Unlabelled session";
  if (RP_META) {
    RP_META.textContent = [
      rpText(identity.started_at_iso, "start time not recorded"),
      rpDuration(identity.total_duration_s) || "duration not recorded",
      rpDuration(identity.monitored_duration_s)
        ? rpDuration(identity.monitored_duration_s) + " monitored" : "not monitored",
    ].join(" · ");
  }

  // Status first: a partial or interrupted report must say so before anything else.
  if (RP_STATUS) {
    if (rep.status === "partial") {
      RP_STATUS.textContent = "PARTIAL — this session is still running, so these figures are incomplete.";
      RP_STATUS.hidden = false;
    } else if (rep.status === "interrupted") {
      RP_STATUS.textContent = "INTERRUPTED — the backend restarted during this session, so up to 10 seconds of data is missing.";
      RP_STATUS.hidden = false;
    } else {
      RP_STATUS.hidden = true;
    }
  }

  // Reliability banner, before any metric it qualifies.
  if (RP_RELIABILITY) {
    rpClear(RP_RELIABILITY);
    RP_RELIABILITY.className = "rp-reliability grade-" + grade.toLowerCase();
    var title = document.createElement("strong");
    title.textContent = "Signal reliability: " + grade;
    RP_RELIABILITY.appendChild(title);
    var reasons = quality.reliability_reasons || [];
    if (reasons.length) {
      var ul = document.createElement("ul");
      reasons.forEach(function (r) {
        var li = document.createElement("li");
        li.textContent = r;
        ul.appendChild(li);
      });
      RP_RELIABILITY.appendChild(ul);
    } else {
      var p = document.createElement("p");
      p.textContent = grade === "GOOD"
        ? "The session produced enough usable signal to describe it in full."
        : "This session is still running, so the figures below are incomplete.";
      RP_RELIABILITY.appendChild(p);
    }
  }

  if (RP_NARRATIVE) {
    rpClear(RP_NARRATIVE);
    (rep.narrative || []).forEach(function (line) {
      var p = document.createElement("p");
      p.textContent = line;
      RP_NARRATIVE.appendChild(p);
    });
  }

  renderReportStats(rep, baseline, quality);
  renderReportTimeline(rep);
  renderReportEpisodes(rep);
  renderReportWarnings(rep);
  renderReportInterventions(rep);
  renderReportProvenance(rep);
  renderReportDownloads(rep);

  if (RP_DISCLAIMER) RP_DISCLAIMER.textContent = rep.disclaimer || "";
  markProvisionalSections(provisional);
}

function markProvisionalSections(provisional) {
  var sections = document.querySelectorAll("#reportPanel .rp-section h3");
  for (var i = 0; i < sections.length; i++) {
    var existing = sections[i].querySelector(".rp-provisional-tag");
    if (provisional && !existing) {
      var tag = document.createElement("span");
      tag.className = "rp-provisional-tag";
      tag.textContent = "provisional";
      sections[i].appendChild(tag);
    } else if (!provisional && existing) {
      existing.remove();
    }
  }
}

function renderReportStats(rep, baseline, quality) {
  if (!RP_STATS) return;
  rpClear(RP_STATS);
  var phys = rep.physiology;
  var hr = (phys && phys.hr) || {};
  var gsr = (phys && phys.gsr) || {};
  var physReason = rpReason(rep, "physiology", "no physiology was recorded");

  RP_STATS.appendChild(rpStat("Baseline HR",
    rpNum(baseline.hr, 0, " bpm"), "calibration never completed",
    "measured over " + (rpDuration(baseline.calibration_duration_s) || "an unknown time")));
  RP_STATS.appendChild(rpStat("Baseline GSR",
    rpNum(baseline.gsr, 0), "calibration never completed", baseline.method || ""));
  RP_STATS.appendChild(rpStat("HR mean / max",
    phys && hr.mean !== null && hr.mean !== undefined
      ? rpNum(hr.mean, 0) + " / " + rpNum(hr.max, 0) + " bpm" : null, physReason));
  RP_STATS.appendChild(rpStat("GSR mean / max",
    phys && gsr.mean !== null && gsr.mean !== undefined
      ? rpNum(gsr.mean, 0) + " / " + rpNum(gsr.max, 0) : null, physReason));
  RP_STATS.appendChild(rpStat("Peak change from baseline",
    phys ? ("HR " + rpText(rpNum(phys.peak_delta_hr, 1)) + " · GSR "
            + rpText(rpNum(phys.peak_delta_gsr, 1))) : null, physReason));
  RP_STATS.appendChild(rpStat("Sample coverage",
    rpNum(quality.coverage_pct, 1, "%"), "no samples were evaluated",
    (quality.samples_evaluated || 0) + " of " + (quality.expected_samples || 0) + " expected"));
  RP_STATS.appendChild(rpStat("Mean confidence",
    rpNum(quality.mean_confidence, 2), "no samples were evaluated",
    "lowest " + rpText(rpNum(quality.min_confidence, 2))));
  RP_STATS.appendChild(rpStat("Connection gaps",
    quality.disconnect_count === null || quality.disconnect_count === undefined
      ? null : String(quality.disconnect_count), "not recorded",
    rpDuration(quality.total_disconnected_s) || "none"));
}

function renderReportTimeline(rep) {
  if (!RP_TIMELINE || !RP_TL_LEGEND) return;
  rpClear(RP_TIMELINE);
  rpClear(RP_TL_LEGEND);
  var states = rep.states;
  if (!states || !states.seconds || !Object.keys(states.seconds).length) {
    RP_TIMELINE.style.display = "none";
    rpMissingSection(RP_TL_LEGEND, rpReason(rep, "states", "no state time was recorded"));
    return;
  }
  RP_TIMELINE.style.display = "flex";
  var order = ["CALM", "STRESS", "ANXIETY", "RECOVERY"];
  var names = Object.keys(states.seconds).sort(function (a, b) {
    return order.indexOf(a) - order.indexOf(b);
  });
  names.forEach(function (name) {
    var pct = (states.pct || {})[name] || 0;
    var seg = document.createElement("div");
    seg.className = "rp-tl-seg state-" + name.toLowerCase();
    seg.style.width = pct + "%";
    seg.title = name + " · " + pct + "%";
    RP_TIMELINE.appendChild(seg);

    var item = document.createElement("div");
    item.className = "rp-tl-item";
    var dot = document.createElement("span");
    dot.className = "rp-tl-dot state-" + name.toLowerCase();
    var text = document.createElement("span");
    text.textContent = name + " — " + (rpDuration(states.seconds[name]) || "0 s") + " (" + pct + "%)";
    item.appendChild(dot);
    item.appendChild(text);
    RP_TL_LEGEND.appendChild(item);
  });
  var changes = document.createElement("div");
  changes.className = "rp-tl-item rp-tl-changes";
  changes.textContent = (states.transition_count || 0) + " state changes";
  RP_TL_LEGEND.appendChild(changes);
}

function renderReportEpisodes(rep) {
  if (!RP_EPISODES) return;
  rpClear(RP_EPISODES);
  // `states` is null exactly when the session had too little evidence to be
  // characterised. Episodes come back as [] there, which must NOT be shown as
  // "none detected" — that would read as a clean result we cannot claim.
  if (!rep.episodes || !rep.states) {
    rpMissingSection(RP_EPISODES, rpReason(rep, "states", "no episodes were recorded"));
    return;
  }
  if (!rep.episodes.length) {
    var p = document.createElement("p");
    p.className = "rp-empty";
    p.textContent = "No stress or anxiety episodes were detected during the monitored window.";
    RP_EPISODES.appendChild(p);
    return;
  }
  rep.episodes.forEach(function (ep) {
    var card = document.createElement("div");
    card.className = "rp-episode state-" + String(ep.kind || "").toLowerCase();
    var head = document.createElement("div");
    head.className = "rp-episode-head";
    head.textContent = "#" + ep.index + " " + ep.kind + " · " + (rpDuration(ep.duration_s) || "?");
    var body = document.createElement("div");
    body.className = "rp-episode-body";
    var bits = [
      "began " + (rpDuration(ep.start_rel) || "?") + " into monitoring",
      "peak HR " + rpText(rpNum(ep.peak_hr, 0, " bpm")),
      "peak alert " + rpText(ep.max_alert_reached, "none"),
      ep.preceded_by_early_warning
        ? ("warned " + rpText(rpNum(ep.lead_time_s, 1, " s")) + " ahead")
        : "no prior warning",
      "ended: " + rpText(ep.resolved_via, "escalated"),
    ];
    if (ep.patterns_observed && ep.patterns_observed.length) {
      bits.push("patterns: " + ep.patterns_observed.join(", "));
    }
    if (ep.intervention_index) {
      bits.push("breathing exercise " + ep.intervention_index + " overlapped");
    }
    body.textContent = bits.join(" · ");
    card.appendChild(head);
    card.appendChild(body);
    RP_EPISODES.appendChild(card);
  });
}

function renderReportWarnings(rep) {
  if (!RP_WARNINGS) return;
  rpClear(RP_WARNINGS);
  var w = rep.early_warnings;
  if (!w) {
    rpMissingSection(RP_WARNINGS, rpReason(rep, "early_warnings", "no forecasts were recorded"));
    return;
  }
  RP_WARNINGS.appendChild(rpStat("Issued", String(w.issued || 0), null,
    "short-horizon forecasts raised"));
  RP_WARNINGS.appendChild(rpStat("Confirmed", String(w.confirmed || 0), null,
    "followed by the predicted state"));
  RP_WARNINGS.appendChild(rpStat("Not followed", String(w.unconfirmed || 0), null,
    "the predicted state did not arrive in the window"));
  RP_WARNINGS.appendChild(rpStat("Median lead time",
    rpNum(w.median_lead_time_s, 1, " s"),
    "no warning was followed by the predicted state"));
}

function renderReportInterventions(rep) {
  if (!RP_INTERV) return;
  rpClear(RP_INTERV);
  var list = rep.interventions || [];
  if (!list.length) {
    var p = document.createElement("p");
    p.className = "rp-empty";
    p.textContent = "No breathing exercise was performed during this session.";
    RP_INTERV.appendChild(p);
    return;
  }
  list.forEach(function (iv) {
    var card = document.createElement("div");
    card.className = "rp-episode";
    var head = document.createElement("div");
    head.className = "rp-episode-head";
    head.textContent = "Exercise #" + iv.index + " · " + rpText(iv.technique)
      + " · " + (rpDuration(iv.actual_duration_s) || "?");
    var grid = document.createElement("div");
    grid.className = "rp-stats";
    grid.appendChild(rpStat("Completion", iv.completion,
      rpReason(rep, "interventions[" + iv.index + "].completion",
               "no planned duration was recorded")));
    grid.appendChild(rpStat("HR change across exercise",
      rpNum(iv.hr_change_bpm, 1, " bpm"), "HR was not recorded",
      "from " + rpText(rpNum(iv.hr_at_start, 0)) + " to " + rpText(rpNum(iv.hr_at_end, 0))));
    grid.appendChild(rpStat("HR 60 s after",
      rpNum(iv.hr_at_plus_60s, 1, " bpm"),
      rpReason(rep, "interventions[" + iv.index + "].hr_at_plus_60s",
               "the observation window did not complete")));
    grid.appendChild(rpStat("State at start / end",
      iv.state_at_start ? (iv.state_at_start + " → " + rpText(iv.state_at_end)) : null,
      "state was not recorded for this exercise"));
    grid.appendChild(rpStat("Returned to CALM in window",
      iv.returned_to_calm_within_window
        ? ("yes, after " + rpText(rpNum(iv.time_to_calm_s, 1, " s"))) : "no", null,
      "observation only"));
    grid.appendChild(rpStat("Recovery data", iv.recovery_data, "the window never opened"));
    card.appendChild(head);
    card.appendChild(grid);
    RP_INTERV.appendChild(card);
  });
}

function renderReportProvenance(rep) {
  if (!RP_PROVENANCE) return;
  rpClear(RP_PROVENANCE);
  var prov = rep.provenance;
  if (!prov) {
    rpMissingSection(RP_PROVENANCE, rpReason(rep, "provenance", "no decisions were recorded"));
    return;
  }
  var pct = prov.fusion_source_pct || {};
  RP_PROVENANCE.appendChild(rpStat("Rules only", rpNum(pct.rules, 1, "%"), "no decisions were recorded"));
  RP_PROVENANCE.appendChild(rpStat("ML only", rpNum(pct.ml, 1, "%"), "the ML model did not contribute"));
  RP_PROVENANCE.appendChild(rpStat("Rules and ML agreed", rpNum(pct.both, 1, "%"),
    "the ML model did not contribute"));
  RP_PROVENANCE.appendChild(rpStat("Rule engine matched the final state",
    rpNum(prov.rule_final_agreement_pct, 1, "%"), "no decisions were recorded"));
  RP_PROVENANCE.appendChild(rpStat("Unstable label flips suppressed",
    String(prov.smoothing_suppressed_flips || 0), null, "by smoothing and the state machine"));
  RP_PROVENANCE.appendChild(rpStat("ML-led ANXIETY decisions",
    String(prov.ml_anxiety_adoptions || 0), null, "model overrode the rules"));
}

function renderReportDownloads(rep) {
  if (!RP_DOWNLOADS) return;
  rpClear(RP_DOWNLOADS);
  var id = rep.identity && rep.identity.id;
  if (!id) return;
  [["JSON", "/session/" + id + "/report"],
   ["HTML", "/session/" + id + "/report.html"],
   ["CSV", "/session/" + id + "/report.csv"]].forEach(function (pair) {
    var a = document.createElement("a");
    a.className = "btn btn-ghost rp-download";
    a.href = pair[1];
    a.textContent = pair[0];
    a.setAttribute("download", "");
    RP_DOWNLOADS.appendChild(a);
  });
}

function openReportPanel() {
  if (!RP_PANEL) return;
  RP_PANEL.hidden = false;
  document.body.classList.add("report-open");
  RP_PANEL.scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeReportPanel() {
  if (!RP_PANEL) return;
  RP_PANEL.hidden = true;
  document.body.classList.remove("report-open");
}

function loadReport(sessionId) {
  return fetch("/session/" + sessionId + "/report")
    .then(function (r) {
      if (!r.ok) throw new Error("report " + r.status);
      return r.json();
    })
    .then(function (rep) { renderReport(rep); openReportPanel(); })
    .catch(function (e) { console.error("report fetch:", e); });
}

function onSessionEnded(sessionId) {
  loadReport(sessionId);
}

function loadSessionsList() {
  if (!SESSIONS_LIST) return;
  fetch("/sessions")
    .then(function (r) { return r.json(); })
    .then(function (items) {
      rpClear(SESSIONS_LIST);
      if (!items.length) {
        var empty = document.createElement("p");
        empty.className = "rp-empty";
        empty.textContent = "No sessions have been recorded yet.";
        SESSIONS_LIST.appendChild(empty);
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement("button");
        row.type = "button";
        row.className = "session-row";
        var title = document.createElement("span");
        title.className = "session-row-title";
        title.textContent = item.label || "Unlabelled session";
        var meta = document.createElement("span");
        meta.className = "session-row-meta";
        meta.textContent = [
          rpText(item.started_at_iso, "time not recorded"),
          rpDuration(item.duration_s) || "duration not recorded",
          rpText(item.reliability, "ungraded"),
          (item.episode_count === null || item.episode_count === undefined)
            ? "episodes not recorded"
            : (item.episode_count + " episode" + (item.episode_count === 1 ? "" : "s")),
        ].join(" · ");
        row.appendChild(title);
        row.appendChild(meta);
        row.addEventListener("click", function () {
          closeSessionsDrawer();
          loadReport(item.id);
        });
        SESSIONS_LIST.appendChild(row);
      });
    })
    .catch(function (e) { console.error("sessions list:", e); });
}

function openSessionsDrawer() {
  if (!SESSIONS_DRAWER) return;
  SESSIONS_DRAWER.hidden = false;
  if (SESSIONS_BACKDROP) SESSIONS_BACKDROP.hidden = false;
  loadSessionsList();
}

function closeSessionsDrawer() {
  if (SESSIONS_DRAWER) SESSIONS_DRAWER.hidden = true;
  if (SESSIONS_BACKDROP) SESSIONS_BACKDROP.hidden = true;
}

if (RP_CLOSE_BTN) RP_CLOSE_BTN.addEventListener("click", closeReportPanel);
if (RP_NEW_BTN) RP_NEW_BTN.addEventListener("click", function () {
  closeReportPanel();
  openSessionStartModal();
});
if (SESSIONS_LIST_BTN) SESSIONS_LIST_BTN.addEventListener("click", openSessionsDrawer);
if (SESSIONS_CLOSE) SESSIONS_CLOSE.addEventListener("click", closeSessionsDrawer);
if (SESSIONS_BACKDROP) SESSIONS_BACKDROP.addEventListener("click", closeSessionsDrawer);

// ── SSE Stream ────────────────────────────────────────────────────────────────
function initStream() {
  let source = new EventSource("/stream");

  source.onmessage = function(event) {
    try {
      const data = JSON.parse(event.data);
      render(data);
    } catch (err) {
      console.error("Parse error:", err);
    }
  };

  source.onerror = function(err) {
    console.error("SSE stream error:", err);
    if (CONN_DOT) { CONN_DOT.classList.remove("ok","warn"); CONN_DOT.classList.add("bad"); }
    if (CONN_TEXT) CONN_TEXT.textContent = "Bluetooth disconnected — reconnecting…";
    if (SW_BANNER) {
      SW_TEXT.textContent = "Connection to server lost";
      SW_BANNER.classList.add("sw-danger");
      SW_BANNER.style.display = "flex";
    }
    source.close();
    setTimeout(initStream, 3000);
  };
}

// ── Boot ──────────────────────────────────────────────────────────────────────
initChart();
initStream();

