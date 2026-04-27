"""
Tier 2: RandomForest on feature vector. Loads model + optional scaler from ml/.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import joblib
import numpy as np

from backend.features import FeatureVector

LOG = logging.getLogger(__name__)

# Training order must match train.py
CLASS_NAMES: List[str] = ["CALM", "STRESS", "ANXIETY", "ACTIVE"]


@dataclass
class MlPrediction:
    label: str
    probabilities: List[float]
    confidence: float


class MlPredictor:
    def __init__(self, model_path: Path, scaler_path: Optional[Path] = None) -> None:
        self._model_path = model_path
        self._scaler_path = scaler_path
        self._model = None
        self._scaler = None
        self._load()

    def _load(self) -> None:
        if not self._model_path.is_file():
            LOG.warning("ML model not found at %s — Tier 2 disabled", self._model_path)
            return
        try:
            self._model = joblib.load(self._model_path)
            LOG.info("Loaded RandomForest from %s", self._model_path)
        except Exception as e:
            LOG.error("Failed to load model: %s", e)
            self._model = None
            return
        if self._scaler_path and self._scaler_path.is_file():
            try:
                self._scaler = joblib.load(self._scaler_path)
                LOG.info("Loaded scaler from %s", self._scaler_path)
            except Exception as e:
                LOG.warning("Scaler load failed (%s), using raw features", e)
                self._scaler = None

    @property
    def available(self) -> bool:
        return self._model is not None

    def predict(self, fv: FeatureVector) -> Optional[MlPrediction]:
        if not self._model:
            return None
        x = np.array(fv.as_list(), dtype=np.float64).reshape(1, -1)
        if self._scaler is not None:
            x = self._scaler.transform(x)
        proba = None
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba(x)[0].tolist()
            idx = int(np.argmax(proba))
            conf = float(proba[idx])
            classes = list(getattr(self._model, "classes_", CLASS_NAMES))
            label = str(classes[idx]) if idx < len(classes) else CLASS_NAMES[0]
        else:
            pred = self._model.predict(x)[0]
            label = str(pred)
            proba = []
            conf = 1.0
        return MlPrediction(label=label, probabilities=proba or [], confidence=conf)
