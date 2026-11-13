"""LiveObservation — one independently sourced market observation (Slice 13 §4.1).

Event time, availability (receive) time and ingestion time are kept separate. UTC only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from markets.lane import DataProvenance, MarketLane, SessionPhase
from shared.versioning.content_hash import hash_json_stable


class FeedEventKind(str, Enum):  # noqa: UP042
    DISCONNECT = "DISCONNECT"
    RECONNECT = "RECONNECT"


def _utc(name: str, v: datetime | None, required: bool = True) -> None:
    if v is None:
        if required:
            raise ValueError(f"{name} is required")
        return
    if v.tzinfo is None or v.utcoffset() != UTC.utcoffset(None):
        raise ValueError(f"{name} must be timezone-aware UTC")


@dataclass(frozen=True)
class LiveObservation:
    lane: MarketLane
    provider_id: str
    instrument_id: str
    venue: str
    event_time: datetime
    available_time: datetime
    ingestion_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    currency: str
    provenance: DataProvenance
    session: SessionPhase = SessionPhase.UNKNOWN
    publication_time: datetime | None = None
    sequence: int | None = None
    revision: int = 0  # 0 = original; >0 = correction of the same identity
    source_ref: str = ""
    feed_entitlement: str = "UNSPECIFIED"
    source_limitations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for n in ("provider_id", "instrument_id", "venue", "currency"):
            if not getattr(self, n) or not str(getattr(self, n)).strip():
                raise ValueError(f"{n} must be non-empty")
        _utc("event_time", self.event_time)
        _utc("available_time", self.available_time)
        _utc("ingestion_time", self.ingestion_time)
        _utc("publication_time", self.publication_time, required=False)
        if self.revision < 0:
            raise ValueError("revision must be >= 0")
        if not isinstance(self.provenance, DataProvenance):
            raise ValueError("provenance must be a DataProvenance")
        # Prices are NOT range-validated here on purpose: invalid values must reach the quality engine
        # and be recorded as rejected, not vanish in a constructor exception. Types are enforced.
        for n in ("open", "high", "low", "close"):
            if not isinstance(getattr(self, n), (int, float)) or isinstance(getattr(self, n), bool):
                raise ValueError(f"{n} must be numeric")
        if not isinstance(self.volume, int) or isinstance(self.volume, bool):
            raise ValueError("volume must be an int")

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (self.provider_id, self.instrument_id, self.venue, self.event_time.isoformat())

    def to_dict(self) -> dict:
        d = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.__dict__.items()}
        d["lane"] = self.lane.value
        d["provenance"] = self.provenance.value
        d["session"] = self.session.value
        d["source_limitations"] = list(self.source_limitations)
        return d

    @staticmethod
    def from_dict(d: dict) -> LiveObservation:
        def dt(x):
            return datetime.fromisoformat(x) if x else None

        return LiveObservation(
            lane=MarketLane(d["lane"]), provider_id=d["provider_id"], instrument_id=d["instrument_id"],
            venue=d["venue"], event_time=dt(d["event_time"]), available_time=dt(d["available_time"]),
            ingestion_time=dt(d["ingestion_time"]), open=d["open"], high=d["high"], low=d["low"],
            close=d["close"], volume=d["volume"], currency=d["currency"],
            provenance=DataProvenance(d["provenance"]), session=SessionPhase(d["session"]),
            publication_time=dt(d.get("publication_time")), sequence=d.get("sequence"),
            revision=d.get("revision", 0), source_ref=d.get("source_ref", ""),
            feed_entitlement=d.get("feed_entitlement", "UNSPECIFIED"),
            source_limitations=tuple(d.get("source_limitations", ())),
        )  # fmt: skip

    def content_hash(self) -> str:
        return hash_json_stable(self.to_dict())

    def price_valid(self) -> bool:
        vals = (self.open, self.high, self.low, self.close)
        if any(isinstance(v, float) and (math.isnan(v) or math.isinf(v)) for v in vals):
            return False
        if any(v <= 0 for v in vals) or self.volume < 0:
            return False
        return self.high >= max(self.open, self.close, self.low) and self.low <= min(
            self.open, self.close, self.high
        )


@dataclass(frozen=True)
class FeedEvent:
    lane: MarketLane
    provider_id: str
    kind: FeedEventKind
    at: datetime

    def __post_init__(self) -> None:
        _utc("at", self.at)
