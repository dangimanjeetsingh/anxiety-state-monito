"""
Fuse rule-based Tier 1 and ML Tier 2; optional confidence gating from config.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.config import MlConfig
from backend.ml_predictor import MlPrediction, MlPredictor


@dataclass
class FusionResult:
    state: str
    rule_state: str
    ml_state: Optional[str]
    source: str  # "ml" | "rules" | "both"


class FusionEngine:
    def __init__(self, ml: MlConfig, predictor: MlPredictor) -> None:
        self._ml_cfg = ml
        self._predictor = predictor

    def fuse(
        self, rule_state: str, ml_pred: Optional[MlPrediction], feature_confidence: float = 1.0
    ) -> FusionResult:
        if ml_pred is None or not self._predictor.available:
            return FusionResult(
                state=rule_state,
                rule_state=rule_state,
                ml_state=None,
                source="rules",
            )
        
        ml_state = ml_pred.label
        effective_confidence = ml_pred.confidence * feature_confidence
        
        # ML model is binary (CALM vs ANXIETY) but rules are multi-class.
        # We only let ML override the rules if it decisively detects ANXIETY.
        if ml_state == "ANXIETY" and effective_confidence >= self._ml_cfg.confidence_fuse:
            source = "both" if rule_state == "ANXIETY" else "ml"
            return FusionResult(
                state="ANXIETY",
                rule_state=rule_state,
                ml_state=ml_state,
                source=source,
            )
        
        # If ML predicts CALM, or confidence is low, DO NOT override rules.
        # The rules may have detected STRESS or ACTIVE which the ML model doesn't know about.
        return FusionResult(
            state=rule_state,
            rule_state=rule_state,
            ml_state=ml_state,
            source="rules",
        )
