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

    def _mock_loop(self) -> None:
        """Simulate plausible HR/GSR for local testing without hardware."""
        import math
        self._on_status("mock", "simulated")
        LOG.info("Mock serial: generating synthetic GSR/HR")
        t0 = time.time()
        
        while not self._stop.is_set():
            elapsed = time.time() - t0

            # Hold calm, low-noise readings during baseline calibration so mock
            # mode matches the documented ~30s calibration window.
            if elapsed < self._mock_calibration_seconds:
                hr = 70.0 + random.uniform(-3.0, 3.0)
                gsr = 500.0 + random.uniform(-10.0, 10.0)
            else:
                # 30-second cycle for pattern generation after calibration
                cycle_elapsed = elapsed - self._mock_calibration_seconds
                cycle_phase = cycle_elapsed % 30.0

                hr = 70.0
                gsr = 500.0 + math.sin(cycle_elapsed * 0.1) * 75.0

                if cycle_phase < 10.0:
                    pass
                elif cycle_phase < 15.0:
                    progress = (cycle_phase - 10.0) / 5.0
                    hr += progress * 25.0
                    gsr += progress * 100.0
                elif cycle_phase < 20.0:
                    hr += 35.0
                    gsr += 150.0
                else:
                    progress = (cycle_phase - 20.0) / 10.0
                    hr += 35.0 * (1.0 - progress)
                    gsr += 150.0 * (1.0 - progress)

                hr += random.uniform(-10.0, 10.0)
                gsr += random.uniform(-20.0, 20.0)

                if random.random() < 0.05:
                    hr += random.uniform(10.0, 20.0)
                    gsr += random.uniform(50.0, 100.0)
                
            line = f"GSR:{int(gsr)},HR:{int(hr)}"
            self._echo(line, "-> HR %6.1f bpm | GSR %6.1f  (mock)" % (hr, gsr))
            self._on_sample(Sample(gsr=gsr, hr=hr, raw_line=line))
            
            # Explicitly lock to 1 update per second
            if self._stop.wait(1.0):
                break
