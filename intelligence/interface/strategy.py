"""The Plane 2 strategy interface. Stage 3 §3.1, §10 (ADR-1).

Every Plane 2 implementation (deterministic baseline, later momentum
factor, later LLM-assisted component) must conform to this shape so
that swapping Plane 2 never requires touching Plane 1 or Plane 3
(FR-6). A strategy is a pure function of (FeatureSnapshots, universe,
previous-universe-state) -> CandidateTrade list; it must not read from
data/adapters, must not make network calls, and must not hold
credentials (§17).
"""

from __future__ import annotations

from typing import Protocol

from data.features.universe import PermittedUniverse
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.trade import CandidateTrade


class Strategy(Protocol):
    """Structural interface every Plane 2 strategy implementation satisfies."""

    strategy_version_id: str

    def generate_candidate_trades(
        self,
        snapshots: list[FeatureSnapshot],
        universe: PermittedUniverse,
        previous_universe: PermittedUniverse | None,
    ) -> list[CandidateTrade]: ...
