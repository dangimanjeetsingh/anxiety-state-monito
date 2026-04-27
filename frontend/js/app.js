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

// ── Chart ────────────────────────────────────────────────────────────────────
const MAX_PTS = 60;
let chart;

function initChart() {
  const ctx = document.getElementById("liveChart");
  if (!ctx) return;
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        { label: "HR (bpm)", data: [], borderColor: "#5c7cfa", backgroundColor: "rgba(92,124,250,0.1)", tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "GSR / 4",  data: [], borderColor: "#a371f7", backgroundColor: "rgba(163,113,247,0.08)", tension: 0.3, pointRadius: 0, borderWidth: 2 },
      ],
    },
    options: {
      responsive: true,
      animation: false,
      scales: {
        x: { ticks: { color: "#9aa3b2", maxTicksLimit: 8 }, grid: { color: "rgba(255,255,255,0.06)" } },
        y: { ticks: { color: "#9aa3b2" }, grid: { color: "rgba(255,255,255,0.06)" } },
      },
      plugins: { legend: { labels: { color: "#e8eaef" } } },
    },
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function stateClass(s) {
  s = (s || "").toUpperCase();
  return { CALM: "state-calm", STRESS: "state-stress", ANXIETY: "state-anxiety", ACTIVE: "state-active" }[s] || "";
}

function clearReadings() {
  if (HR_EL)  HR_EL.textContent  = "—";
  if (GSR_EL) GSR_EL.textContent = "—";
  if (STATE_EL) STATE_EL.textContent = "—";
  if (STATE_CARD) STATE_CARD.classList.remove("state-calm", "state-stress", "state-anxiety", "state-active");
  if (META_EL) META_EL.textContent = "";
}

function setConn(conn, detail) {
  if (!CONN_DOT || !CONN_TEXT) return;
  CONN_DOT.classList.remove("ok", "warn", "bad");
  const c = (conn || "").toLowerCase();
  if (c === "connected" || c === "mock") {
    CONN_DOT.classList.add("ok");
    CONN_TEXT.textContent = c === "mock" ? "Mock serial (no hardware)" : "Bluetooth connected";
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

// ── Main render ───────────────────────────────────────────────────────────────
function render(d) {
  const age = d.server_time ? ((Date.now()/1000 - d.server_time).toFixed(1) + "s old") : "?";

  // If no sensor data is arriving, blank the value boxes and bail early
  const conn = (d.connection || "").toLowerCase();
  if (conn === "no_data" || conn === "disconnected") {
    clearReadings();
    setConn(d.connection, d.connection_detail);
    setSensorWarning(d.sensor_warning || null);
    return;
  }
  console.log("[" + new Date().toLocaleTimeString() + "] HR=" + d.hr + " GSR=" + d.gsr + " state=" + d.state + " data=" + age);

  if (HR_EL)  HR_EL.textContent  = d.hr  != null ? Math.round(d.hr)  : "--";
  if (GSR_EL) GSR_EL.textContent = d.gsr != null ? Math.round(d.gsr) : "--";

  if (STATE_EL) STATE_EL.textContent = d.state || "--";
  if (STATE_CARD) {
    STATE_CARD.classList.remove("state-calm","state-stress","state-anxiety","state-active");
    var cls = stateClass(d.state);
    if (cls) STATE_CARD.classList.add(cls);
  }

  if (META_EL)
    META_EL.textContent = "Rules: " + (d.rule_state||"--") + " · ML: " + (d.ml_state||"--") + " · " + (d.fusion_source||"--");

  setConn(d.connection, d.connection_detail);
  setSensorWarning(d.sensor_warning || null);

  if (BASELINE_INFO)
    BASELINE_INFO.textContent = (d.baseline_hr != null && d.baseline_gsr != null)
      ? "Baseline HR " + Math.round(d.baseline_hr) + " · GSR " + Math.round(d.baseline_gsr)
      : "Baseline calibrating...";
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
