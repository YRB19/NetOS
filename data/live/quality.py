"""Observation quality engine (Slice 13 §4.5). Never invents, fills or zeroes a price."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from data.live.observation import FeedEvent, FeedEventKind, LiveObservation
from markets.lane import MarketLane


class QualityVerdict(str, Enum):  # noqa: UP042
    ACCEPTED = "ACCEPTED"
    CORRECTION_ACCEPTED = "CORRECTION_ACCEPTED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"  # accepted into the store, flagged; never reorders history
    LATE = "LATE"  # available too long after event time: stored, NOT usable for decisions
    STALE = "STALE"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    UNSUPPORTED_INSTRUMENT = "UNSUPPORTED_INSTRUMENT"
    WRONG_LANE = "WRONG_LANE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"


USABLE = {QualityVerdict.ACCEPTED, QualityVerdict.CORRECTION_ACCEPTED, QualityVerdict.OUT_OF_ORDER}


class SessionHealth(str, Enum):  # noqa: UP042
    OK = "OK"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class QualityPolicy:
    lane: MarketLane
    currency: str
    supported_instruments: frozenset[str]
    required_instruments: frozenset[str]
    max_event_to_available_lag: timedelta
    max_staleness: timedelta
    degrade_missing_fraction: float  # >= this fraction of required instruments missing -> DEGRADED
    block_missing_fraction: float  # >= this -> BLOCKED
    max_feed_gap: timedelta

    def __post_init__(self) -> None:
        if not 0 <= self.degrade_missing_fraction <= self.block_missing_fraction <= 1:
            raise ValueError("require 0 <= degrade <= block <= 1")
        if not self.required_instruments <= self.supported_instruments:
            raise ValueError("required instruments must be supported")


@dataclass(frozen=True)
class QualityDecision:
    verdict: QualityVerdict
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.verdict in USABLE


@dataclass
class QualityEngine:
    policy: QualityPolicy
    _seen: dict = field(default_factory=dict)  # identity -> highest revision
    _latest_event: dict = field(default_factory=dict)  # instrument -> latest event_time
    _last_seen_usable: dict = field(default_factory=dict)  # instrument -> available_time
    counts: dict = field(default_factory=dict)
    feed_events: list = field(default_factory=list)

    def assess(self, o: LiveObservation) -> QualityDecision:
        d = self._assess(o)
        self.counts[d.verdict.value] = self.counts.get(d.verdict.value, 0) + 1
        return d

    def _assess(self, o: LiveObservation) -> QualityDecision:
        p = self.policy
        if o.lane is not p.lane:
            return QualityDecision(QualityVerdict.WRONG_LANE, f"{o.lane.value} observation in {p.lane.value}")
        if o.currency != p.currency:
            return QualityDecision(QualityVerdict.CURRENCY_MISMATCH, f"{o.currency} != {p.currency}")
        if o.instrument_id not in p.supported_instruments:
            return QualityDecision(QualityVerdict.UNSUPPORTED_INSTRUMENT, o.instrument_id)
        if o.available_time < o.event_time or (
            o.publication_time is not None and o.publication_time > o.available_time
        ):
            return QualityDecision(QualityVerdict.INVALID_TIMESTAMP, "availability precedes event/publication")
        if o.ingestion_time < o.available_time:
            return QualityDecision(QualityVerdict.INVALID_TIMESTAMP, "ingestion precedes availability")
        if not o.price_valid():
            return QualityDecision(QualityVerdict.INVALID_PRICE, "non-positive/non-finite/inconsistent OHLC")
        prev = self._seen.get(o.identity)
        if prev is not None:
            if o.revision <= prev:
                return QualityDecision(QualityVerdict.DUPLICATE, f"revision {o.revision} <= seen {prev}")
            self._seen[o.identity] = o.revision
            self._touch(o)
            return QualityDecision(QualityVerdict.CORRECTION_ACCEPTED, f"revision {o.revision}")
        if o.available_time - o.event_time > p.max_event_to_available_lag:
            self._seen[o.identity] = o.revision
            return QualityDecision(QualityVerdict.LATE, "event->availability lag exceeds policy")
        self._seen[o.identity] = o.revision
        latest = self._latest_event.get(o.instrument_id)
        self._touch(o)
        if latest is not None and o.event_time < latest:
            return QualityDecision(QualityVerdict.OUT_OF_ORDER, "event_time earlier than latest accepted")
        return QualityDecision(QualityVerdict.ACCEPTED)

    def _touch(self, o: LiveObservation) -> None:
        cur = self._latest_event.get(o.instrument_id)
        if cur is None or o.event_time > cur:
            self._latest_event[o.instrument_id] = o.event_time
        self._last_seen_usable[o.instrument_id] = o.available_time

    def record_feed_event(self, e: FeedEvent) -> None:
        self.feed_events.append(e)

    def stale_instruments(self, now: datetime) -> tuple[str, ...]:
        """Required instruments with no usable observation within max_staleness. Never filled."""
        out = []
        for i in sorted(self.policy.required_instruments):
            t = self._last_seen_usable.get(i)
            if t is None or now - t > self.policy.max_staleness:
                out.append(i)
        return tuple(out)

    def health(self, now: datetime) -> tuple[SessionHealth, dict]:
        p = self.policy
        stale = self.stale_instruments(now)
        frac = len(stale) / len(p.required_instruments) if p.required_instruments else 0.0
        open_disc = self._open_disconnect(now)
        detail = {"missing_or_stale": list(stale), "missing_fraction": frac,
                  "open_disconnect_seconds": open_disc}  # fmt: skip
        if frac >= p.block_missing_fraction and p.required_instruments:
            return SessionHealth.BLOCKED, detail
        if open_disc is not None and open_disc > p.max_feed_gap.total_seconds():
            return SessionHealth.BLOCKED, detail
        if frac >= p.degrade_missing_fraction and frac > 0:
            return SessionHealth.DEGRADED, detail
        return SessionHealth.OK, detail

    def _open_disconnect(self, now: datetime) -> float | None:
        last = None
        for e in self.feed_events:
            last = e
        if last is not None and last.kind is FeedEventKind.DISCONNECT:
            return (now - last.at).total_seconds()
        return None
