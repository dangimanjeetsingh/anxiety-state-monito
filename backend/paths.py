"""Project root resolution — no hardcoded absolute paths."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Directory containing app.py (repository root)."""
    # backend/paths.py -> parent is backend -> parent is project root
    return Path(__file__).resolve().parent.parent


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    return ensure_dir(project_root() / "data")


def logs_dir() -> Path:
    return ensure_dir(data_dir() / "logs")


def ml_dir() -> Path:
    return ensure_dir(project_root() / "ml")


def model_path() -> Path:
    return ml_dir() / "model.pkl"


def scaler_path() -> Path:
    return ml_dir() / "scaler.pkl"
