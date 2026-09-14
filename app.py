"""
Entry point: `python app.py` from project root.
Loads config, starts Bluetooth/mock reader thread, runs Flask dashboard.
"""
from __future__ import annotations

import logging
import os
import sys

# Ensure project root is importable when run as script
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.config import load_config
from backend.flask_app import create_app
from backend.state_service import AnxietyStateService


def _setup_logging() -> None:
    level = os.environ.get("ANXIETY_LOG_LEVEL", "INFO").upper()
    resolved = getattr(logging, level, logging.INFO)
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Flask logs one line per HTTP request. The dashboard polls /stream and
    # re-fetches its assets continuously, so at INFO this buries everything
    # else -- including the live sensor feed -- at several lines a second.
    # Warnings and errors still come through; set ANXIETY_LOG_LEVEL=DEBUG to
    # see the request log again.
    if resolved > logging.DEBUG:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)


def main() -> None:
    _setup_logging()
    log = logging.getLogger("anxiety_app")
    cfg = load_config()
    # The raw feed is on unless explicitly silenced. `--echo` is kept so the
    # older instructions still work, and `--quiet` turns it off for a demo run.
    if any(a in ("--quiet", "-q") for a in sys.argv[1:]):
        cfg.serial.echo_serial = False
    elif any(a in ("--echo", "-e") for a in sys.argv[1:]):
        cfg.serial.echo_serial = True
    # Demo switches: `--mock` runs the scripted generator with no hardware,
    # `--scenario NAME` picks which script, `--speed N` compresses its clock.
    args = sys.argv[1:]
    if any(a in ("--mock", "-m") for a in args):
        cfg.serial.use_mock = True
    for i, a in enumerate(args):
        if a == "--scenario" and i + 1 < len(args):
            cfg.serial.mock_scenario = args[i + 1].strip().lower()
            cfg.serial.use_mock = True
        elif a.startswith("--scenario="):
            cfg.serial.mock_scenario = a.split("=", 1)[1].strip().lower()
            cfg.serial.use_mock = True
        elif a == "--speed" and i + 1 < len(args):
            cfg.serial.mock_speed = float(args[i + 1])
        elif a.startswith("--speed="):
            cfg.serial.mock_speed = float(a.split("=", 1)[1])

    service = AnxietyStateService(cfg)
    service.start_reader()
    app = create_app(service)
    host = os.environ.get("ANXIETY_HOST", "127.0.0.1")
    port = int(os.environ.get("ANXIETY_PORT", "5000"))
    log.info("Dashboard: http://%s:%s/", host, port)
    if cfg.serial.use_mock:
        log.info(
            "MOCK MODE: scenario=%s speed=%.2fx (choices: demo, calm, stress, anxiety, activity, recovery)",
            cfg.serial.mock_scenario, cfg.serial.mock_speed,
        )
    else:
        log.info("COM port (set ANXIETY_COM_PORT): %s", cfg.serial.port)
    if cfg.serial.echo_serial:
        log.info("Raw serial echo: ON - every line from the device is printed below")
    else:
        log.info("Raw serial echo: off (--quiet). Drop --quiet to see live device lines.")
    
    try:
        app.run(host=host, port=port, threaded=True, use_reloader=False)
    finally:
        service.stop_reader()


if __name__ == "__main__":
    main()
