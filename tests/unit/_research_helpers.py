"""SYNTHETIC fixtures for research-harness tests. None of this is real market data and
nothing built from it is evidence of trading performance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from data.features.universe import make_permitted_universe
from domain.models.enums import Action
from domain.models.market_data import MarketData
from domain.models.trade import CandidateTrade
from research.harness.config import EvaluationPeriod, ResearchConfig, two_way_split
from shared.versioning.versioning import content_hash

BASE = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)  # after v2 schedule effective date (2026-03-01)
ISINS = ("INE000A00001", "INE000B00002", "INE000C00003")
V1 = "india-equity-v1-unverified"
V2 = "india-equity-v2-2026-03-verified"


def day(n: int) -> datetime:
    return BASE + timedelta(days=n)


def bar(
    isin: str, n: int, close: float, open_: float | None = None, source="SYNTHETIC"
) -> MarketData:
    o = close - 0.5 if open_ is None else open_
    hi, lo = max(o, close) + 1, min(o, close) - 1
    return MarketData(isin, day(n), o, hi, lo, close, 1000, source, BASE, "synthetic-v1")


def make_bars(isins=ISINS, days=10, price=lambda i, d: 100.0 * (i + 1) + d, skip=()):
    out = []
    for d in range(days):
        for i, isin in enumerate(isins):
            if (isin, d) in skip:
                continue
            out.append(bar(isin, d, price(i, d)))
    return out


def universe(isins=ISINS, effective=0):
    return make_permitted_universe(list(isins), day(effective))


def config(**over) -> ResearchConfig:
    split = two_way_split(day(-30), day(-1), day(0), day(9))
    args = dict(
        hypothesis="SYNTHETIC: harness plumbing check, not a performance claim",
        pre_registered_criteria="SYNTHETIC: none; run is infrastructure verification only",
        initial_capital="1000000",
        cost_schedule_version=V2,
        split=split,
        evaluation_period=EvaluationPeriod.OUT_OF_SAMPLE,
    )
    args.update(over)
    return ResearchConfig(**args)


class ThresholdStrategy:
    """Test-only strategy: BUY (equal weight) while reference_price > threshold, else HOLD.
    Its output depends on price LEVEL, so leaked future prices would change its decisions."""

    strategy_version_id = "test_threshold_strategy_v1"

    def __init__(self, threshold: float = 150.0) -> None:
        self.threshold = threshold
        self.seen_snapshots: list = []

    def generate_candidate_trades(self, snapshots, universe, previous_universe):
        self.seen_snapshots.extend(snapshots)
        out = []
        w = 1.0 / len(universe.instrument_ids)
        for s in snapshots:
            buy = s.is_complete and s.reference_price > self.threshold
            out.append(_cand(s, Action.BUY if buy else Action.HOLD, w if buy else None,
                             self.strategy_version_id))  # fmt: skip
        return out


def _cand(s, action, hint, version, rationale="synthetic test strategy", candidate_id=None):
    digest = content_hash((s.snapshot_id, version, action.value))
    return CandidateTrade(
        candidate_id=candidate_id or str(UUID((digest * 2)[:32])),
        instrument_id=s.instrument_id,
        timestamp=s.decision_timestamp,
        action=action,
        size_hint=hint,
        confidence=1.0 if action is not Action.HOLD else 0.5,
        uncertainty_band=None,
        rationale=rationale,
        input_snapshot_id=s.snapshot_id,
        strategy_version_id=version,
        model_version_id=None,
    )


class CallbackStrategy:
    """Test-only strategy delegating to a function (for malformed-output injection)."""

    def __init__(self, fn, version="test_callback_strategy_v1") -> None:
        self.fn, self.strategy_version_id = fn, version

    def generate_candidate_trades(self, snapshots, universe, previous_universe):
        return self.fn(snapshots, universe, previous_universe)
