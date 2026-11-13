"""Independent outcome evaluator. Reads frozen predictions + independently captured observations.

It cannot modify predictions, observations, strategies or execution state: it imports only the READ-ONLY
ledger reader and observation reader. Simulated/external-paper fills are never consulted for market truth.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from data.live.observation import LiveObservation
from data.live.reader import ObservationReader
from markets.lane import DataProvenance, MarketLane
from prediction_ledger.models import ConfidenceSemantics, Direction
from prediction_ledger.reader import LedgerReader, PredictionView
from research.prediction_eval import metrics as M


class ResultCategory(str, Enum):  # noqa: UP042
    PREDICTION = "PREDICTION_OUTCOME"
    INTERNAL_PORTFOLIO = "INTERNAL_PAPER_PORTFOLIO_OUTCOME"
    EXTERNAL_PLATFORM = "EXTERNAL_PAPER_PLATFORM_OUTCOME"


class Unscored(str, Enum):  # noqa: UP042
    NOT_MATURED = "NOT_MATURED"
    NOT_SCOREABLE = "NOT_SCOREABLE_STATUS"
    NO_REFERENCE_PRICE = "NO_REFERENCE_PRICE"
    NO_END_PRICE = "NO_END_PRICE"
    NO_BENCHMARK_DATA = "NO_BENCHMARK_DATA"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    CORPORATE_ACTION_IN_WINDOW = "CORPORATE_ACTION_IN_WINDOW"
    SOURCE_DISAGREEMENT = "SOURCE_DISAGREEMENT"


@dataclass(frozen=True)
class PredictionOutcome:
    prediction_id: str
    scored: bool
    reason: Unscored | None
    realized_direction: Direction | None = None
    hit: bool | None = None
    instrument_return: float | None = None
    benchmark_return: float | None = None
    relative_return: float | None = None
    provenances: tuple[str, ...] = ()
    observation_hashes: tuple[str, ...] = ()
    cross_check: str = "NOT_AVAILABLE"  # NOT_AVAILABLE | MATCH | MISMATCH | NOT_INDEPENDENT
    independence: str = "SINGLE_SOURCE"
    corporate_action_check: str = "NOT_VERIFIED"


def _ref(obs: list[LiveObservation], t: datetime, max_gap_s: float):
    c = [o for o in obs if o.event_time >= t and (o.event_time - t).total_seconds() <= max_gap_s]
    return c[0] if c else None


def _end(obs: list[LiveObservation], t: datetime, after: datetime, max_gap_s: float):
    c = [o for o in obs if after < o.event_time <= t and (t - o.event_time).total_seconds() <= max_gap_s]
    return c[-1] if c else None


@dataclass
class OutcomeEvaluator:
    lane: MarketLane
    ledger: LedgerReader
    observations: ObservationReader
    second_source: ObservationReader | None = None
    corporate_actions: Callable[[str, datetime, datetime], bool] | None = None  # True if action in window
    cross_check_tolerance_bps: float = 25.0

    def __post_init__(self) -> None:
        if self.ledger.lane is not self.lane or self.observations.lane is not self.lane:
            raise ValueError("ledger and observations must belong to the evaluator's lane")
        if self.second_source is not None and self.second_source.lane is not self.lane:
            raise ValueError("second source must belong to the same lane")

    def evaluate(self, as_of: datetime) -> list[PredictionOutcome]:
        return [self._one(v, as_of) for v in self.ledger.views()]

    def _one(self, v: PredictionView, as_of: datetime) -> PredictionOutcome:
        r = v.record
        if not v.scoreable:
            return PredictionOutcome(r.prediction_id, False, Unscored.NOT_SCOREABLE)
        if r.valid_until > as_of:
            return PredictionOutcome(r.prediction_id, False, Unscored.NOT_MATURED)
        od = r.outcome_definition
        ref_gap, end_gap = float(od.get("max_ref_gap_seconds", 0)), float(od.get("max_end_gap_seconds", 0))
        band = float(od.get("flat_band_bps", 0)) / 1e4

        def series(inst: str, rd: ObservationReader):
            return [o for o in rd.usable_as_of(as_of, inst)]

        def ret(rd: ObservationReader, inst: str):
            s = series(inst, rd)
            a, b = _ref(s, r.valid_from, ref_gap), None
            if a is not None:
                b = _end(s, r.valid_until, a.event_time, end_gap)
            return a, b

        ia, ib = ret(self.observations, r.instrument_id)
        if ia is None:
            return PredictionOutcome(r.prediction_id, False, Unscored.NO_REFERENCE_PRICE)
        if ib is None:
            return PredictionOutcome(r.prediction_id, False, Unscored.NO_END_PRICE)
        ba, bb = ret(self.observations, r.benchmark_instrument_id)
        if ba is None or bb is None:
            return PredictionOutcome(r.prediction_id, False, Unscored.NO_BENCHMARK_DATA)
        if any(o.currency != r.currency for o in (ia, ib, ba, bb)):
            return PredictionOutcome(r.prediction_id, False, Unscored.CURRENCY_MISMATCH)
        ca = "NOT_VERIFIED"
        if self.corporate_actions is not None:
            if self.corporate_actions(r.instrument_id, ia.event_time, ib.event_time) or self.corporate_actions(
                r.benchmark_instrument_id, ba.event_time, bb.event_time
            ):
                return PredictionOutcome(r.prediction_id, False, Unscored.CORPORATE_ACTION_IN_WINDOW,
                                         corporate_action_check="ACTION_IN_WINDOW")  # fmt: skip
            ca = "NO_ACTION_IN_WINDOW"
        cross, indep = "NOT_AVAILABLE", "SINGLE_SOURCE"
        if self.second_source is not None:
            sa, sb = ret(self.second_source, r.instrument_id)
            if sa is not None and sb is not None:
                if sb.provider_id == ib.provider_id:
                    cross = "NOT_INDEPENDENT"
                else:
                    indep = "TWO_SOURCES"
                    diff = abs(sb.close / ib.close - 1) * 1e4
                    cross = "MATCH" if diff <= self.cross_check_tolerance_bps else "MISMATCH"
                    if cross == "MISMATCH":
                        return PredictionOutcome(r.prediction_id, False, Unscored.SOURCE_DISAGREEMENT,
                                                 cross_check=cross, independence=indep)  # fmt: skip
        # Outcome uses ONLY the declared price field (close) from independently captured observations.
        ri = ib.close / ia.close - 1
        rb = bb.close / ba.close - 1
        rel = ri - rb
        realized = Direction.UP if rel > band else Direction.DOWN if rel < -band else Direction.FLAT
        obs = (ia, ib, ba, bb)
        return PredictionOutcome(
            r.prediction_id, True, None, realized, realized == r.direction, ri, rb, rel,
            tuple(sorted({o.provenance.value for o in obs})), tuple(o.content_hash() for o in obs),
            cross, indep, ca,
        )  # fmt: skip


def evidence_class(outcomes: Iterable[PredictionOutcome], source_verified: bool) -> str:
    """LIVE_DATA_SHADOW only if every scored outcome used LIVE data AND the source is verified."""
    prov = {p for o in outcomes if o.scored for p in o.provenances}
    if not prov:
        return "NO_SCORED_OUTCOMES"
    if prov == {DataProvenance.LIVE.value} and source_verified:
        return "LIVE_DATA_SHADOW"
    if DataProvenance.SYNTHETIC.value in prov:
        return "SYNTHETIC_ENGINEERING"
    return "ENGINEERING_REPLAY_OR_UNVERIFIED_SOURCE"


@dataclass(frozen=True)
class CoverageInputs:
    eligible_opportunities: int
    mirrored_external_orders: int = 0
    platform_rejections: int = 0
    unreconciled_platform_events: int = 0
    late_or_unavailable_data_events: int = 0


def coverage_report(lane: MarketLane, ledger: LedgerReader, outcomes: list[PredictionOutcome], inp: CoverageInputs) -> dict:
    by_status = Counter(v.record.status.value for v in ledger.views())
    reasons = Counter(o.reason.value for o in outcomes if not o.scored and o.reason)
    return {
        "lane": lane.value, "category": ResultCategory.PREDICTION.value,
        "eligible_opportunities": inp.eligible_opportunities,
        "predictions_generated": by_status.get("ISSUED", 0), "no_signal": by_status.get("NO_SIGNAL", 0),
        "invalid_outputs": by_status.get("INVALID_OUTPUT", 0), "rejected_outputs": by_status.get("REJECTED_OUTPUT", 0),
        "provider_failures": by_status.get("PROVIDER_FAILED", 0),
        "data_unavailable_predictions": by_status.get("DATA_UNAVAILABLE", 0),
        "late_or_unavailable_data_events": inp.late_or_unavailable_data_events,
        "late_committed_rejected": sum(1 for v in ledger.views() if v.late_rejected),
        "invalidated": sum(1 for v in ledger.views() if v.invalidated),
        "unscored": sum(1 for o in outcomes if not o.scored), "unscored_reasons": dict(sorted(reasons.items())),
        "matured_scored": sum(1 for o in outcomes if o.scored),
        "mirrored_external_orders": inp.mirrored_external_orders, "platform_rejections": inp.platform_rejections,
        "unreconciled_platform_events": inp.unreconciled_platform_events,
    }  # fmt: skip


def summarize(lane: MarketLane, ledger: LedgerReader, outcomes: list[PredictionOutcome], min_n: int) -> dict:
    views = {v.record.prediction_id: v.record for v in ledger.views()}
    sc = [o for o in outcomes if o.scored]
    n, hits = len(sc), sum(1 for o in sc if o.hit)
    out: dict = {"lane": lane.value, "category": ResultCategory.PREDICTION.value, "scored_n": n,
                 "min_n_required": min_n}  # fmt: skip
    if n < min_n:
        out["status"] = "INSUFFICIENT_SAMPLE"
        out["note"] = "descriptive counts only; no interval or inferential claim"
        out["hits"] = hits
        return out
    out["status"] = "SUFFICIENT_FOR_DESCRIPTION"
    out["hit_rate"] = hits / n
    out["hit_rate_wilson_95"] = M.wilson_interval(hits, n)
    out["mean_relative_return"] = sum(o.relative_return for o in sc) / n
    pairs = [(views[o.prediction_id].score, o.relative_return) for o in sc if views[o.prediction_id].score is not None]
    out["rank_ic"] = M.spearman_ic([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
    cal = [o for o in sc if views[o.prediction_id].confidence_semantics is ConfidenceSemantics.CALIBRATED_PROBABILITY_CLAIMED]
    ps = [views[o.prediction_id].confidence for o in cal]
    ys = [1 if o.hit else 0 for o in cal]
    out["brier"], out["log_loss"] = M.brier(ps, ys), M.log_loss(ps, ys)
    out["probabilistic_n"] = len(cal)
    out["probabilistic_note"] = "Brier/log-loss use only predictions that CLAIM calibrated-probability semantics"
    return out  # fmt: skip
