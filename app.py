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
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    _setup_logging()
    log = logging.getLogger("anxiety_app")
    cfg = load_config()
    service = AnxietyStateService(cfg)
    service.start_reader()
    app = create_app(service)
    host = os.environ.get("ANXIETY_HOST", "127.0.0.1")
    port = int(os.environ.get("ANXIETY_PORT", "5000"))
    log.info("Dashboard: http://%s:%s/", host, port)
    log.info("COM port (set ANXIETY_COM_PORT): %s", cfg.serial.port)
    try:
        app.run(host=host, port=port, threaded=True, use_reloader=False)
    finally:
        service.stop_reader()


if __name__ == "__main__":
    main()
