"""Data-layer freshness classification (SF-2 machinery).

Stage 3 §5: "Historical ingestion is not a live-feed system... implement the
freshness/staleness abstraction needed by the architecture so the same concept can later be
used by live ingestion." This module is that abstraction's data-layer entry point: it
classifies a MarketData record as FRESH or STALE relative to a reference instant and an
operator-configurable threshold, and states plainly that stale data must be treated as missing
(SF-1's path), never as current — it does not decide what happens next (that is a live-pipeline
concern for a future slice); it only produces the classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from domain.models.market_data import MarketData
from shared.time.clock import evaluate_freshness


class FreshnessClassification(Enum):
    FRESH = "FRESH"
    STALE = "STALE"  # per SF-2: must be routed to the same handling as SF-1 (missing data)


@dataclass(frozen=True)
class FreshnessCheckResult:
    classification: FreshnessClassification
    age_seconds: float
    threshold_seconds: float


def classify_market_data_freshness(
    record: MarketData,
    *,
    threshold_seconds: float,
    reference_time: datetime | None = None,
) -> FreshnessCheckResult:
    """Classify one MarketData record as FRESH or STALE.

    `threshold_seconds` is deliberately a required, explicit parameter with no built-in
    default — per Stage 3 §5, "If a freshness threshold is configurable, do not hardcode an
    operator trading threshold." This module has no opinion on what the right threshold is for
    live trading; it only implements the mechanism.
    """
    result = evaluate_freshness(
        record.timestamp, threshold_seconds=threshold_seconds, reference_time=reference_time
    )
    classification = (
        FreshnessClassification.FRESH if result.is_fresh else FreshnessClassification.STALE
    )
    return FreshnessCheckResult(
        classification=classification,
        age_seconds=result.age_seconds,
        threshold_seconds=threshold_seconds,
    )
