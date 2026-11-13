"""LaneShadowSession: one lane's observation capture, prediction recording and execution mirroring."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from data.live.observation import FeedEvent, LiveObservation
from data.live.quality import QualityEngine, QualityPolicy
from data.live.reader import ObservationReader
from data.live.store import ObservationStore
from domain.models.market_data import MarketData
from markets.lane import LANE_SPECS, DataProvenance, MarketLane
from markets.readiness import LaneReadiness, LaneStatus
from observability.prediction_ledger.ledger import PredictionLedger
from prediction_ledger.models import PredictionEventType, PredictionRecord
from risk_execution.external_paper.contract import ApprovedIntent
from risk_execution.external_paper.mirror import ExternalLedger, ExternalMirror, ExternalOrderRecord
from simulation.multi_market.sessions import Tier


class InternalPathBlocked(Exception):  # noqa: N818
    pass


@dataclass
class LaneShadowSession:
    root: Path
    lane: MarketLane
    policy: QualityPolicy
    readiness: LaneReadiness
    engine: QualityEngine = field(init=False)
    store: ObservationStore = field(init=False)
    ledger: PredictionLedger = field(init=False)

    def __post_init__(self) -> None:
        if self.policy.lane is not self.lane or self.readiness.lane is not self.lane:
            raise ValueError("policy and readiness must belong to the session lane")
        self.engine = QualityEngine(self.policy)
        self.store = ObservationStore(self.root, self.lane)
        self.ledger = PredictionLedger(self.root, self.lane)

    # ---- data capture (independent of AI, strategies and execution) ----
    def ingest(self, items: Iterable[LiveObservation | FeedEvent]) -> dict:
        for it in items:
            if isinstance(it, FeedEvent):
                self.engine.record_feed_event(it)
            else:
                self.store.append(it, self.engine.assess(it))
        return dict(self.engine.counts)

    def reader(self) -> ObservationReader:
        return ObservationReader(self.root, self.lane)

    def market_data(self, as_of: datetime) -> list[MarketData]:
        """Canonical MarketData built ONLY from usable, point-in-time observations. Provenance is carried
        in `source` so a REPLAY/SYNTHETIC run can never be mistaken for live."""
        out = []
        for o in self.reader().usable_as_of(as_of):
            out.append(MarketData(o.instrument_id, o.event_time, float(o.open), float(o.high), float(o.low),
                                  float(o.close), o.volume, f"{o.provenance.value}:{o.provider_id}",
                                  o.ingestion_time, f"obsstore-{self.reader().head_hash[:12]}"))  # fmt: skip
        return out

    # ---- AI predictions: recorded separately; no path into strategies or orders ----
    def record_prediction(self, rec: PredictionRecord, recorded_at: datetime) -> PredictionEventType:
        return self.ledger.record(rec, recorded_at)

    # ---- deterministic strategy execution: injected, existing PipelineHarness ----
    def run_internal(self, tier: Tier, runner: Callable[[list[MarketData]], object], as_of: datetime):
        if self.readiness.internal_execution_status is LaneStatus.BLOCKED:
            raise InternalPathBlocked(
                f"{self.lane.value} internal simulated execution is BLOCKED: " + "; ".join(self.readiness.reasons)
            )
        return runner(self.market_data(as_of))

    # ---- external comparator ----
    def intents_from(self, orders: Iterable[dict]) -> list[ApprovedIntent]:
        rd = self.reader()
        out = []
        for o in orders:
            ts = o["decision_timestamp"]
            ref = [x for x in rd.usable_as_of(ts, o["instrument_id"])]
            px = ref[-1].close if ref else None
            out.append(ApprovedIntent(self.lane, o["instrument_id"], o["side"], int(o["quantity"]), "MARKET",
                                      o["order_id"], o["idempotency_key"], o["risk_decision_id"], px))  # fmt: skip
        return out

    def mirror(self, intents: Iterable[ApprovedIntent], mirror: ExternalMirror) -> list[ExternalOrderRecord]:
        return [mirror.mirror(i) for i in intents]


def new_external_ledger(lane: MarketLane) -> ExternalLedger:
    return ExternalLedger(currency=LANE_SPECS[lane].currency)


_ = DataProvenance
