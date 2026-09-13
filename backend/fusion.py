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
        
        # The ML model is binary (CALM vs ANXIETY) while the rules are multi-class.
        # It reliably separates "elevated" from "calm", but its confidence does not
        # distinguish mild stress from full arousal, so it corroborates the rules'
        # ANXIETY rather than promoting STRESS to ANXIETY on its own. Set
        # ANXIETY_ML_ALLOW_ESCALATION=1 to restore the overriding behaviour.
        if ml_state == "ANXIETY" and effective_confidence >= self._ml_cfg.confidence_fuse:
            if rule_state == "ANXIETY":
                return FusionResult(
                    state="ANXIETY",
                    rule_state=rule_state,
                    ml_state=ml_state,
                    source="both",
                )
            if self._ml_cfg.allow_escalation:
                return FusionResult(
                    state="ANXIETY",
                    rule_state=rule_state,
                    ml_state=ml_state,
                    source="ml",
                )
        
        # If ML predicts CALM, or confidence is low, DO NOT override rules.
        # The rules may have detected STRESS or ACTIVE which the ML model doesn't know about.
        return FusionResult(
            state=rule_state,
            rule_state=rule_state,
            ml_state=ml_state,
            source="rules",
        )
