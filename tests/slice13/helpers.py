from __future__ import annotations

from datetime import UTC, datetime, timedelta

from data.live.observation import LiveObservation
from data.live.quality import QualityPolicy
from markets.lane import DataProvenance, MarketLane
from prediction_ledger.models import (
    ConfidenceSemantics, Designation, Direction, PredictionRecord, PredictionStatus,
)  # fmt: skip

T0 = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
CUR = {MarketLane.US_EQUITIES: "USD", MarketLane.IN_EQUITIES: "INR"}


def obs(lane=MarketLane.US_EQUITIES, inst="AAA", t=T0, close=100.0, lag=0, prov=DataProvenance.SYNTHETIC,
        provider="SYNTH_A", revision=0, **kw) -> LiveObservation:  # fmt: skip
    avail = t + timedelta(seconds=lag)
    return LiveObservation(
        lane=lane, provider_id=provider, instrument_id=inst, venue="XTST", event_time=t, available_time=avail,
        ingestion_time=avail, open=close, high=close * 1.01, low=close * 0.99, close=close, volume=1000,
        currency=CUR[lane], provenance=prov, revision=revision, **kw,
    )  # fmt: skip


def policy(lane=MarketLane.US_EQUITIES, insts=("AAA", "BBB", "SPY"), required=("AAA", "BBB")):
    return QualityPolicy(lane, CUR[lane], frozenset(insts), frozenset(required), timedelta(seconds=60),
                         timedelta(seconds=300), 0.25, 0.75, timedelta(seconds=120))  # fmt: skip


def pred(pid="p1", lane=MarketLane.US_EQUITIES, inst="AAA", direction=Direction.UP, created=T0,
         valid_from=None, horizon=timedelta(hours=1), status=PredictionStatus.ISSUED, **kw) -> PredictionRecord:
    vf = valid_from or created + timedelta(minutes=1)
    if status is not PredictionStatus.ISSUED:
        direction = None
    return PredictionRecord(
        prediction_id=pid, correlation_id="c-" + pid, lane=lane, instrument_id=inst, universe_version="u1",
        session_id="s1", created_at=created, input_available_at=created, valid_from=vf, valid_until=vf + horizon,
        horizon_label="1h", forecast_target="DIRECTION_VS_BENCHMARK", status=status, benchmark_id="B1",
        benchmark_instrument_id="SPY", currency=CUR[lane], calendar_id="cal", protocol_id="proto1",
        designation=Designation.EXPLORATORY, evidence_class="SYNTHETIC_ENGINEERING", direction=direction,
        outcome_definition={"price_field": "close", "flat_band_bps": 10, "max_ref_gap_seconds": 120,
                            "max_end_gap_seconds": 120},
        confidence_semantics=kw.pop("confidence_semantics", ConfidenceSemantics.UNDEFINED), **kw,
    )  # fmt: skip
