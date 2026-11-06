"""Deterministic confidence-adjustment overlay on a base strategy (Slice 11).

The model's output can change ONE thing: `CandidateTrade.confidence`, by a bounded, versioned,
operator/research-configured amount. Action, size_hint, instrument, universe, ranking, quantity,
risk and execution are never touched. When there is no usable signal the ORIGINAL candidate object
is returned unchanged (identity), so AI-disabled and no-signal runs are byte-identical to baseline.

Direction: the model reports relative to a LONG thesis (see schema). For BUY candidates the
adjustment follows it; for SELL candidates it is inverted (a positive disclosure lowers confidence
in a SELL). HOLD candidates are never adjusted.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from data.features.universe import PermittedUniverse
from domain.models.enums import Action
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.trade import CandidateTrade
from domain.models.versions import ModelVersion
from intelligence.llm_component.schema import Adjustment, Materiality
from intelligence.llm_component.signals import SignalRecord
from shared.versioning.versioning import content_hash, make_version_id

ADJUSTMENT_VERSION = "confidence_adjustment_v1"
_DEFAULT_WEIGHTS = (("HIGH", 1.0), ("MEDIUM", 0.5), ("LOW", 0.25), ("NONE", 0.0))


@dataclass(frozen=True)
class ConfidenceAdjustmentConfig:
    """Predeclared research parameters. The MODEL cannot set or widen any of these."""

    max_delta: float = 0.10
    min_model_confidence: float = 0.60
    materiality_weights: tuple[tuple[str, float], ...] = _DEFAULT_WEIGHTS
    version: str = ADJUSTMENT_VERSION

    def validate(self) -> list[str]:
        errs = []
        if not (isinstance(self.max_delta, (int, float)) and math.isfinite(self.max_delta)
                and 0.0 <= self.max_delta <= 0.5):  # fmt: skip
            errs.append("max_delta must be within [0, 0.5]")
        if not (0.0 <= self.min_model_confidence <= 1.0):
            errs.append("min_model_confidence must be within [0, 1]")
        for k, w in self.materiality_weights:
            if k not in {m.value for m in Materiality} or not (0.0 <= w <= 1.0):
                errs.append(f"invalid materiality weight {k!r}={w!r}")
        return errs

    def payload(self) -> dict:
        return {"max_delta": self.max_delta, "min_model_confidence": self.min_model_confidence,
                "materiality_weights": [list(x) for x in self.materiality_weights], "version": self.version}  # fmt: skip

    def weight(self, m: Materiality) -> float:
        return dict(self.materiality_weights).get(m.value, 0.0)


@dataclass(frozen=True)
class AdjustmentOutcome:
    applied: bool
    reason: str
    original_confidence: float
    adjusted_confidence: float
    delta: float


def adjust_candidate(
    cand: CandidateTrade, rec: SignalRecord | None, cfg: ConfidenceAdjustmentConfig,
    model_version: ModelVersion, overlay_strategy_version_id: str,
) -> tuple[CandidateTrade, AdjustmentOutcome]:  # fmt: skip
    """Pure. Returns (candidate, outcome); the original object when nothing is applied."""

    def _no(reason: str):  # noqa: ANN202
        return cand, AdjustmentOutcome(False, reason, cand.confidence, cand.confidence, 0.0)

    if rec is None:
        return _no("NO_SIGNAL_RECORD")
    if not rec.has_signal:
        return _no(f"NO_ADJUSTMENT:{rec.provider_status.value}")
    it = rec.interpretation
    if cand.action is Action.HOLD:
        return _no("HOLD_NOT_ADJUSTED")
    if it.confidence < cfg.min_model_confidence:
        return _no("LOW_MODEL_CONFIDENCE")
    if it.confidence_adjustment is Adjustment.NO_CHANGE:
        return _no("NEUTRAL_SENTIMENT")
    weight = cfg.weight(it.materiality)
    if weight == 0.0 or cfg.max_delta == 0.0:
        return _no("ZERO_WEIGHT")
    sign = 1.0 if it.confidence_adjustment is Adjustment.INCREASE else -1.0
    if cand.action is Action.SELL:
        sign = -sign
    delta = sign * cfg.max_delta * weight * it.confidence
    new_conf = min(1.0, max(0.0, cand.confidence + delta))
    if new_conf == cand.confidence:
        return _no("CLAMPED_NO_CHANGE")
    digest = content_hash(
        [cand.candidate_id, model_version.version_id, rec.context_hash, cfg.payload()]
    )
    new = replace(
        cand,
        candidate_id=str(UUID((digest * 2)[:32])),
        confidence=new_conf,
        rationale=(
            f"{cand.rationale} | AI research signal (RESEARCH SIGNAL ONLY; confidence "
            f"{cand.confidence:.4f}->{new_conf:.4f}, {it.sentiment.value}/{it.materiality.value}, "
            f"docs={len(it.source_document_refs)}, {cfg.version})"
        ),  # fmt: skip
        model_version_id=model_version.version_id,
    )
    return new, AdjustmentOutcome(
        True, "APPLIED", cand.confidence, new_conf, new_conf - cand.confidence
    )


class DisclosureOverlayStrategy:
    """Wraps a base Strategy. Pure: only looks up precomputed SignalRecords; no network, no I/O."""

    def __init__(self, base, lookup: Callable[[str, datetime], SignalRecord | None],  # noqa: ANN001
                 cfg: ConfidenceAdjustmentConfig, model_version: ModelVersion) -> None:  # fmt: skip
        errs = cfg.validate()
        if errs:
            raise ValueError("invalid ConfidenceAdjustmentConfig: " + "; ".join(errs))
        if model_version.parent_strategy_version != base.strategy_version_id:
            raise ValueError(
                "ModelVersion.parent_strategy_version must equal the base strategy_version_id"
            )
        self.base, self._lookup, self.cfg, self.model_version = base, lookup, cfg, model_version
        self.base_strategy_version_id = base.strategy_version_id
        # The pipeline requires candidate.strategy_version_id == the run's strategy id, and baseline provenance
        # must be preserved, so the run-facing id stays the BASE id. The overlay's own distinct identity
        # (base + model version + adjustment config) is `overlay_version_id`, journaled with every signal.
        self.strategy_version_id = base.strategy_version_id
        self.overlay_version_id = make_version_id(
            "ai_disclosure_overlay_v1",
            {
                "base": base.strategy_version_id,
                "model_version": model_version.version_id,
                "adjustment": cfg.payload(),
            },
        )
        self.expected_feature_set_id = getattr(base, "expected_feature_set_id", None)
        self._prov: dict[str, dict] = {}

    def strategy_version(self):  # noqa: ANN201
        from domain.models.versions import Plane2Type, StrategyVersion

        return StrategyVersion(Plane2Type.LLM, self.overlay_version_id, version_id=self.overlay_version_id,
                               parent_version=self.base_strategy_version_id)  # fmt: skip

    def generate_candidate_trades(self, snapshots: list[FeatureSnapshot], universe: PermittedUniverse,
                                  previous_universe: PermittedUniverse | None) -> list[CandidateTrade]:  # fmt: skip
        out: list[CandidateTrade] = []
        for cand in self.base.generate_candidate_trades(snapshots, universe, previous_universe):
            rec = self._lookup(cand.instrument_id, cand.timestamp)
            new, outcome = adjust_candidate(
                cand, rec, self.cfg, self.model_version, self.overlay_version_id
            )
            self._prov[new.candidate_id] = {
                "original_candidate_id": cand.candidate_id, "baseline_strategy_version_id": self.base_strategy_version_id,
                "overlay_strategy_version_id": self.overlay_version_id, "model_version_id": self.model_version.version_id,
                "adjustment_version": self.cfg.version, "adjustment_config": self.cfg.payload(),
                "applied": outcome.applied, "outcome_reason": outcome.reason,
                "original_confidence": outcome.original_confidence, "adjusted_confidence": outcome.adjusted_confidence,
                "confidence_delta": outcome.delta, "original_action": cand.action, "original_size_hint": cand.size_hint,
                "signal": rec.to_payload() if rec else None, "label": "RESEARCH SIGNAL ONLY",
            }  # fmt: skip
            out.append(new)
        return out

    def provenance_for(self, candidate: CandidateTrade) -> dict | None:
        """Journal hook (duck-typed by the pipeline): the AI provenance of this exact candidate."""
        return self._prov.get(candidate.candidate_id)
