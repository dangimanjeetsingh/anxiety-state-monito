"""
Bluetooth / serial reader for HC-05. Parses lines like: GSR:520,HR:72
Handles invalid payloads (e.g. 'Place finger'), disconnects, and optional mock stream.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None  # type: ignore

from backend.config import SerialConfig

LOG = logging.getLogger(__name__)

# A separate logger so the raw feed can be silenced or redirected on its own
# without touching the rest of the backend's logging.
RAW_LOG = logging.getLogger("saarthi.serial")

# Looser regex to match GSR and HR anywhere in the line, allowing floats and alternate names
_GSR_RE = re.compile(r"(?:GSR|BSP)\s*[:=]\s*([+-]?\d*(?:\.\d+)?)", re.IGNORECASE)
_HR_RE = re.compile(r"(?:HR|BPM)\s*[:=]\s*([+-]?\d*(?:\.\d+)?)", re.IGNORECASE)


@dataclass
class Sample:
    gsr: float
    hr: float
    raw_line: str


class BluetoothReader:
    """
    Background thread reads serial port and pushes samples via callback.
    On disconnect, clears state and retries with backoff.
    """

    def __init__(
        self,
        config: SerialConfig,
        on_sample: Callable[[Sample], None],
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
        *,
        mock_calibration_seconds: float = 30.0,
    ) -> None:
        self._cfg = config
        self._on_sample = on_sample
        self._on_status = on_status or (lambda *_: None)
        self._mock_calibration_seconds = max(0.0, mock_calibration_seconds)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ser: Optional[object] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="bt-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_serial()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _close_serial(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception as e:
                LOG.debug("serial close: %s", e)
            self._ser = None

    def _run_loop(self) -> None:
        if self._cfg.use_mock:
            self._mock_loop()
            return
        if serial is None:
            LOG.error("pyserial not installed; enable ANXIETY_USE_MOCK_SERIAL=1")
            self._on_status("error", "pyserial missing")
            return
        self._last_sample_ts: float = 0.0
        while not self._stop.is_set():
            self._on_status("connecting", self._cfg.port)
            try:
                self._ser = serial.Serial(
                    self._cfg.port,
                    self._cfg.baudrate,
                    timeout=self._cfg.timeout_s,
                )
                self._on_status("connected", self._cfg.port)
                LOG.info("Serial open %s @ %s", self._cfg.port, self._cfg.baudrate)
                self._last_sample_ts = time.time()
                self._read_serial()
            except Exception as e:
                LOG.warning("Serial error: %s", e)
                self._on_status("disconnected", str(e))
                self._close_serial()
                if self._stop.wait(self._cfg.reconnect_delay_s):
                    break
            else:
                self._on_status("disconnected", "closed")
                self._close_serial()
                if self._stop.wait(self._cfg.reconnect_delay_s):
                    break

    _NO_DATA_TIMEOUT_S: float = 5.0   # seconds of silence → warn UI

    def _read_serial(self) -> None:
        assert self._ser is not None
        buf = ""
        _warned_no_data = False
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(256)
                if not chunk:
                    # Check for data-silence timeout
                    silence = time.time() - self._last_sample_ts
                    if silence > self._NO_DATA_TIMEOUT_S and not _warned_no_data:
                        self._on_status("no_data", f"No data for {int(silence)}s")
                        _warned_no_data = True
                    continue
                buf += chunk.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    self._handle_line(line.strip())
            except Exception as e:
                LOG.warning("Read loop: %s", e)
                self._on_status("disconnected", str(e))
                break

    def _echo(self, raw: str, parsed: Optional[str] = None) -> None:
        """Print one inbound line to the terminal when echo is enabled."""
        if not self._cfg.echo_serial:
            return
        RAW_LOG.info("%-28s %s", raw, parsed or "")

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        lower = line.lower()
        if "finger" in lower or "place" in lower or "wait" in lower:
            LOG.debug("Device message: %s", line)
            self._echo(line, "-> ignored (device message)")
            # Surface this to the UI as a sensor warning
            self._on_status("sensor_warning", "Place finger on sensor")
            return
        m_gsr = _GSR_RE.search(line)
        m_hr = _HR_RE.search(line)

        if not m_gsr or not m_hr:
            LOG.debug("Unparseable line: %s", line)
            self._echo(line, "-> dropped (no GSR/HR match)")
            return
        try:
            gsr = float(m_gsr.group(1))
            hr = float(m_hr.group(1))
        except ValueError:
            self._echo(line, "-> dropped (non-numeric value)")
            return
        self._echo(line, "-> HR %6.1f bpm | GSR %6.1f" % (hr, gsr))
        # Good data received — reset silence tracking & restore connected status
        self._last_sample_ts = time.time()
        self._on_status("connected", None)
        self._on_sample(Sample(gsr=gsr, hr=hr, raw_line=line))

    # ------------------------------------------------------------------
    # Mock (demonstration) stream
    # ------------------------------------------------------------------
    #
    # Why the mock is scripted rather than a short sine cycle:
    # compute_features() averages a 30 s sliding window and compares that mean
    # to the calibrated baseline. A 5 s spike of +35 bpm only lifts the window
    # mean by ~6 bpm, which never clears ANXIETY_THR_DELTA_HR (12) — the old
    # cycle could physically only ever reach STRESS. Every elevated phase below
    # therefore holds its plateau for well over one window, so the window mean
    # itself lands in the intended band, and the noise is kept small so the
    # confidence gate (rules downgrade below 0.5) stays clear.
    #
    # A phase is (name, duration_s, hr_delta_start, hr_delta_end,
    #             gsr_delta_start, gsr_delta_end), deltas relative to the calm
    # resting point the baseline calibrates on.
    _MOCK_BASE_HR: float = 70.0
    _MOCK_BASE_GSR: float = 500.0
    _MOCK_HR_NOISE: float = 1.2
    _MOCK_GSR_NOISE: float = 5.0

    # Full arc: every state the FSM can show, in order, each held long enough
    # for the smoother (majority of 7) and the FSM hold timers to commit.
    _MOCK_DEMO_PHASES = [
        ("calm",        45.0,  0.0,  0.0,   0.0,   0.0),
        ("onset",       25.0,  0.0, 10.0,   0.0,  55.0),
        ("stress",      45.0, 10.0, 10.0,  55.0,  55.0),
        ("escalation",  16.0, 10.0, 42.0,  55.0, 230.0),
        ("anxiety",     90.0, 42.0, 42.0, 230.0, 230.0),
        ("deescalate",  12.0, 42.0, -9.0, 230.0, -70.0),
        ("rebound",     40.0, -9.0, -9.0, -70.0, -70.0),
        ("recovery",    45.0, -9.0,  0.0, -70.0,   0.0),
        ("settled",     30.0,  0.0,  0.0,   0.0,   0.0),
        # Motor activity: HR climbs with no sympathetic GSR surge, which is the
        # ACTIVE rule (delta_gsr stays under ANXIETY_THR_ACTIVITY_GSR_DELTA=25).
        ("activity",    45.0,  0.0, 30.0,   0.0,  10.0),
        ("cooldown",    35.0, 30.0,  0.0,  10.0,   0.0),
    ]

    # Single-state scenarios: ramp in, then hold forever (last phase repeats).
    _MOCK_SCENARIOS = {
        "demo": _MOCK_DEMO_PHASES,
        "calm": [("calm", 60.0, 0.0, 0.0, 0.0, 0.0)],
        "stress": [
            ("onset", 25.0, 0.0, 10.0, 0.0, 55.0),
            ("stress", 120.0, 10.0, 10.0, 55.0, 55.0),
        ],
        "anxiety": [
            ("onset", 20.0, 0.0, 10.0, 0.0, 55.0),
            ("stress", 25.0, 10.0, 10.0, 55.0, 55.0),
            ("escalation", 16.0, 10.0, 42.0, 55.0, 230.0),
            ("anxiety", 180.0, 42.0, 42.0, 230.0, 230.0),
        ],
        "activity": [
            ("activity", 45.0, 0.0, 30.0, 0.0, 10.0),
            ("activity_hold", 120.0, 30.0, 30.0, 10.0, 10.0),
        ],
        "recovery": [
            ("escalation", 30.0, 0.0, 42.0, 0.0, 230.0),
            ("anxiety", 60.0, 42.0, 42.0, 230.0, 230.0),
            ("deescalate", 12.0, 42.0, -9.0, 230.0, -70.0),
            ("rebound", 40.0, -9.0, -9.0, -70.0, -70.0),
            ("recovery", 45.0, -9.0, 0.0, -70.0, 0.0),
            ("settled", 60.0, 0.0, 0.0, 0.0, 0.0),
        ],
    }

    def _mock_phases(self) -> list:
        name = getattr(self._cfg, "mock_scenario", "demo") or "demo"
        phases = self._MOCK_SCENARIOS.get(name)
        if phases is None:
            LOG.warning(
                "Unknown ANXIETY_MOCK_SCENARIO=%r; falling back to 'demo' (choices: %s)",
                name, ", ".join(sorted(self._MOCK_SCENARIOS)),
            )
            phases = self._MOCK_DEMO_PHASES
        return list(phases)

    def _mock_phase_at(self, phases: list, t: float) -> tuple:
        """Resolve scripted time *t* to (phase_name, hr_delta, gsr_delta)."""
        total = sum(p[1] for p in phases)
        looping = getattr(self._cfg, "mock_loop", True)
        if total <= 0:
            return "calm", 0.0, 0.0
        if t >= total:
            if looping:
                t = t % total
            else:
                # Hold the end of the script rather than snapping back to calm.
                name, _dur, _h0, h1, _g0, g1 = phases[-1]
                return name, h1, g1
        acc = 0.0
        for name, dur, h0, h1, g0, g1 in phases:
            if t < acc + dur:
                progress = (t - acc) / dur if dur > 0 else 1.0
                return (
                    name,
                    h0 + (h1 - h0) * progress,
                    g0 + (g1 - g0) * progress,
                )
            acc += dur
        name, _dur, _h0, h1, _g0, g1 = phases[-1]
        return name, h1, g1

    def _mock_loop(self) -> None:
        """Replay a scripted physiological scenario for demos without hardware."""
        self._on_status("mock", "simulated")
        phases = self._mock_phases()
        speed = max(0.1, float(getattr(self._cfg, "mock_speed", 1.0) or 1.0))
        scenario = getattr(self._cfg, "mock_scenario", "demo")
        LOG.info(
            "Mock serial: scenario=%s speed=%.2fx loop=%s (%.0fs script, %.0fs calibration first)",
            scenario, speed, getattr(self._cfg, "mock_loop", True),
            sum(p[1] for p in phases), self._mock_calibration_seconds,
        )
        t0 = time.time()
        last_phase: Optional[str] = None

        while not self._stop.is_set():
            elapsed = time.time() - t0

            if elapsed < self._mock_calibration_seconds:
                # Quiet, low-variance resting period so the baseline locks on
                # the same resting point every phase below is measured against.
                phase = "calibrating"
                hr_delta = 0.0
                gsr_delta = 0.0
            else:
                script_t = (elapsed - self._mock_calibration_seconds) * speed
                phase, hr_delta, gsr_delta = self._mock_phase_at(phases, script_t)

            if phase != last_phase:
                LOG.info("Mock scenario phase: %s", phase)
                last_phase = phase

            hr = self._MOCK_BASE_HR + hr_delta + random.gauss(0.0, self._MOCK_HR_NOISE)
            gsr = self._MOCK_BASE_GSR + gsr_delta + random.gauss(0.0, self._MOCK_GSR_NOISE)

            line = f"GSR:{int(gsr)},HR:{int(hr)}"
            self._echo(line, "-> HR %6.1f bpm | GSR %6.1f  (mock: %s)" % (hr, gsr, phase))
            self._on_sample(Sample(gsr=gsr, hr=hr, raw_line=line))

            # Explicitly lock to 1 update per second
            if self._stop.wait(1.0):
                break
