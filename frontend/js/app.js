// ── DOM refs ────────────────────────────────────────────────────────────────
const HR_EL         = document.getElementById("hrVal");
const GSR_EL        = document.getElementById("gsrVal");
const STATE_EL      = document.getElementById("stateVal");
const META_EL       = document.getElementById("metaVal");
const STATE_CARD    = document.getElementById("stateCard");
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

// ── Chart ────────────────────────────────────────────────────────────────────
const MAX_PTS = 60;
let chart;
let recoveryChart;

function initChart() {
  const ctx = document.getElementById("liveChart");
  if (!ctx) return;
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        { label: "HR (bpm)", data: [], borderColor: "#5c7cfa", backgroundColor: "rgba(92,124,250,0.12)", tension: 0.35, pointRadius: 0, borderWidth: 2.2, fill: true },
        { label: "GSR / 4",  data: [], borderColor: "#a371f7", backgroundColor: "rgba(163,113,247,0.08)", tension: 0.35, pointRadius: 0, borderWidth: 2.2, fill: true },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { ticks: { color: "#9aa3b2", maxTicksLimit: 8 }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { ticks: { color: "#9aa3b2" }, grid: { color: "rgba(255,255,255,0.05)" } },
      },
      plugins: { legend: { labels: { color: "#e8eaef", font: { size: 12, weight: "600" }, padding: 12 } } },
    },
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function stateClass(s) {
  s = (s || "").toUpperCase();
  return { CALM: "state-calm", STRESS: "state-stress", ANXIETY: "state-anxiety", RECOVERY: "state-recovery", ACTIVE: "state-active" }[s] || "";
}

function clearReadings() {
  if (HR_EL)  HR_EL.textContent  = "—";
  if (GSR_EL) GSR_EL.textContent = "—";
  if (STATE_EL) STATE_EL.textContent = "—";
  if (STATE_CARD) STATE_CARD.classList.remove("state-calm", "state-stress", "state-anxiety", "state-recovery", "state-active");
  if (META_EL) META_EL.textContent = "";
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

// ── Calibration Status ────────────────────────────────────────────────────────
function setCalibrationStatus(d) {
  if (!CAL_BANNER || !CAL_TITLE || !CAL_MESSAGE || !CAL_STATUS) return;

  const conn = (d.connection || "").toLowerCase();
  const connected = conn === "connected" || conn === "mock";
  const hasReading = d.hr != null && d.gsr != null;
  const calibrated = d.calibrated === true;
  const isMock = conn === "mock";

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
  } else if (!calibrated) {
    CAL_TITLE.textContent = isMock ? "Mock baseline calibration (~30s)" : "Baseline calibration in progress";
    CAL_MESSAGE.textContent = isMock
      ? "Mock data generator active. Calibrating baseline over initial 30 seconds. Predictions will start automatically when ready."
      : "Please sit calmly, keep your hand still, and breathe normally. Your personal baseline is being measured; predictions will start when it is ready.";
    CAL_STATUS.textContent = "Calibrating";
  } else {
    CAL_TITLE.textContent = "Baseline complete";
    CAL_MESSAGE.textContent = isMock
      ? "Synthetic baseline complete. Live mock predictions and trend warnings are now active."
      : "Your personal baseline is ready. Live state predictions are now active.";
    CAL_STATUS.textContent = "Prediction active";
  }
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
function updatePredictionBanner(d) {
  if (!PRED_BANNER || !PRED_TITLE || !PRED_DETAIL || !PRED_COUNTDOWN) return;

  const pred = d.prediction;
  if (d.calibrated === true && pred && pred.active === true && pred.seconds_to_transition != null) {
    const sec = Math.max(1, Math.round(pred.seconds_to_transition));
    const target = pred.predicted_state || "STRESS";
    PRED_TITLE.textContent = "Trending toward " + target + " in ~" + sec + "s";
    PRED_DETAIL.textContent = pred.basis
      ? "Early forecast basis: " + pred.basis + " (linear projection capped at 30s)"
      : "Linear trend projection based on physiological slope indicators.";
    PRED_COUNTDOWN.textContent = "~" + sec + "s";
    PRED_BANNER.style.display = "flex";
  } else {
    PRED_BANNER.style.display = "none";
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

function logExerciseBackend(event) {
  fetch("/session/exercise", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event: event, timestamp: Date.now() / 1000 }),
  }).catch(e => console.debug("Exercise log marker error:", e));
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
          borderColor: "#3fb950",
          backgroundColor: "rgba(63,185,80,0.12)",
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 2,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#9aa3b2", maxTicksLimit: 6 }, grid: { display: false } },
        y: { ticks: { color: "#9aa3b2" }, grid: { color: "rgba(255,255,255,0.05)" } },
      },
      plugins: {
        legend: { labels: { color: "#e8eaef", font: { size: 11 } } },
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

  const calibrating = !d.calibrated && (conn === "connected" || conn === "mock");
  if (STATE_EL) STATE_EL.textContent = calibrating ? "CALIBRATING" : (d.state || "—");
  if (STATE_CARD) {
    STATE_CARD.classList.remove("state-calm","state-stress","state-anxiety","state-recovery","state-active");
    var cls = calibrating ? "" : stateClass(d.state);
    if (cls) STATE_CARD.classList.add(cls);
  }

  if (META_EL)
    META_EL.textContent = calibrating
      ? "Sit calmly — prediction starts after calibration"
      : "Rules: " + (d.rule_state||"—") + " · ML: " + (d.ml_state||"—") + " · " + (d.fusion_source||"—");

  setConn(d.connection, d.connection_detail);
  setSensorWarning(d.sensor_warning || null);

  if (BASELINE_INFO)
    BASELINE_INFO.textContent = d.calibrated && d.baseline_hr != null && d.baseline_gsr != null
      ? "Baseline HR " + Math.round(d.baseline_hr) + " · GSR " + Math.round(d.baseline_gsr)
      : "Baseline calibration in progress — sit calmly";
  if (WINDOW_INFO)
    WINDOW_INFO.textContent = d.window_samples != null
      ? "Window: " + d.window_samples + " samples · calibrated: " + d.calibrated
      : "";

  if (chart && d.hr != null && d.gsr != null) {
    var t = new Date().toLocaleTimeString();
    chart.data.labels.push(t);
    chart.data.datasets[0].data.push(d.hr);
    chart.data.datasets[1].data.push(d.gsr / 4);
    if (chart.data.labels.length > MAX_PTS) {
      chart.data.labels.shift();
      chart.data.datasets[0].data.shift();
      chart.data.datasets[1].data.shift();
    }
    chart.update("none");
  }

  if (BP_PROMPT) {
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

