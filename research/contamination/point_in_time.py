"""Point-in-time availability (Slice 9, ADR-16).

Four different times are kept apart: the market/event time (`MarketData.timestamp`), the
source availability time (`available_at`, only when evidenced), the system ingestion time
(`MarketData.ingestion_time`, pipeline provenance) and the decision time. `ingestion_time`
is NEVER silently promoted to an availability time. Observations whose availability is
UNKNOWN are excluded (or the run fails, per policy) and reported as UNVERIFIABLE; they never
become a clean point-in-time claim. Revisions are explicit: at decision time t the latest
revision whose `available_at <= t` is the only one visible.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from domain.models.market_data import MarketData
from research.harness.failures import FailureCategory, ResearchRunFailure
from shared.versioning.content_hash import hash_json_stable


class AvailabilityBasis(str, Enum):  # noqa: UP042
    SOURCE_PUBLISHED = "SOURCE_PUBLISHED"  # source supplied a publication/availability time
    INGESTION_RECORDED = "INGESTION_RECORDED"  # captured live; ingestion time evidenced as arrival
    SYNTHETIC_DECLARED = "SYNTHETIC_DECLARED"  # synthetic fixture with explicit declared time
    UNKNOWN = "UNKNOWN"  # legacy: no evidence — never backfilled


class UnknownAvailabilityPolicy(str, Enum):  # noqa: UP042
    EXCLUDE = "EXCLUDE"  # exclude affected records and report them
    FAIL = "FAIL"  # fail the run closed


class PitStatus(str, Enum):  # noqa: UP042
    VERIFIED = "VERIFIED"
    VERIFIED_INGESTION_BASED = "VERIFIED_INGESTION_BASED"
    SYNTHETIC = "SYNTHETIC"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True)
class VersionedObservation:
    market_data: MarketData
    revision: int = 0
    available_at: datetime | None = None
    basis: AvailabilityBasis = AvailabilityBasis.UNKNOWN
    note: str | None = None

    def __post_init__(self) -> None:
        if self.basis is AvailabilityBasis.UNKNOWN and self.available_at is not None:
            raise ValueError("available_at given but basis is UNKNOWN; state the evidence basis")
        if self.basis is not AvailabilityBasis.UNKNOWN and self.available_at is None:
            raise ValueError(f"basis {self.basis.value} requires available_at")
        if self.available_at is not None and self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("revision must be a non-negative int")

    @property
    def key(self) -> tuple[str, datetime]:
        return (self.market_data.instrument_id, self.market_data.timestamp)


def _fp(o: VersionedObservation) -> list:
    m = o.market_data
    return [m.instrument_id, m.timestamp.isoformat(), m.source, o.revision,
            o.available_at.isoformat() if o.available_at else None, o.basis.value,
            m.open, m.high, m.low, m.close, m.volume, m.adjusted]  # fmt: skip


class AvailabilityLedger:
    def __init__(self, observations: Iterable[VersionedObservation],
                 unknown_policy: UnknownAvailabilityPolicy = UnknownAvailabilityPolicy.EXCLUDE) -> None:  # fmt: skip
        obs = list(observations)
        if not obs:
            raise ResearchRunFailure(FailureCategory.MISSING_DATA, "availability ledger is empty")
        self.unknown_policy = unknown_policy
        self._by_key: dict[tuple[str, datetime], list[VersionedObservation]] = defaultdict(list)
        seen: set[tuple[str, datetime, int]] = set()
        for o in obs:
            k3 = (o.key[0], o.key[1], o.revision)
            if k3 in seen:
                raise ResearchRunFailure(
                    FailureCategory.DUPLICATE_DATA,
                    f"duplicate revision {o.revision} for {o.key[0]} at {o.key[1].isoformat()}",
                )
            seen.add(k3)
            self._by_key[o.key].append(o)
        for lst in self._by_key.values():
            lst.sort(key=lambda x: x.revision)
        self.observations = sorted(obs, key=lambda o: (o.key[1], o.key[0], o.revision))
        self.instrument_ids = frozenset(k[0] for k in self._by_key)
        self.unknown = [o for o in self.observations if o.basis is AvailabilityBasis.UNKNOWN]
        if self.unknown and unknown_policy is UnknownAvailabilityPolicy.FAIL:
            raise ResearchRunFailure(
                FailureCategory.CONTAMINATION,
                f"{len(self.unknown)} observation(s) have UNKNOWN source availability; policy FAIL",
                unverifiable=[f"{o.key[0]}@{o.key[1].isoformat()}" for o in self.unknown[:20]],
            )

    # ---------------------------------------------------------------- resolve
    def resolve_one(self, instrument_id: str, ts: datetime, as_of: datetime) -> MarketData | None:
        if ts > as_of:
            return None
        best: VersionedObservation | None = None
        for o in self._by_key.get((instrument_id, ts), ()):
            if o.available_at is not None and o.available_at <= as_of:
                best = o  # sorted by revision: the last qualifying one is the latest known
        return best.market_data if best else None

    def resolve(self, as_of: datetime) -> list[MarketData]:
        out = []
        for (inst, ts) in sorted(self._by_key, key=lambda k: (k[1], k[0])):
            if ts > as_of:
                break
            md = self.resolve_one(inst, ts, as_of)
            if md is not None:
                out.append(md)
        return out

    def revised_keys(self) -> list[tuple[str, datetime]]:
        return sorted(k for k, v in self._by_key.items() if len(v) > 1)

    def status(self) -> PitStatus:
        bases = {o.basis for o in self.observations}
        if AvailabilityBasis.UNKNOWN in bases:
            return PitStatus.UNVERIFIABLE
        if bases == {AvailabilityBasis.SYNTHETIC_DECLARED}:
            return PitStatus.SYNTHETIC
        if AvailabilityBasis.INGESTION_RECORDED in bases:
            return PitStatus.VERIFIED_INGESTION_BASED
        return PitStatus.VERIFIED

    def fingerprint(self) -> str:
        return hash_json_stable([_fp(o) for o in self.observations])

    def latest_market_data(self) -> list[MarketData]:
        """Latest revision per key, regardless of when it became available (for versioning)."""
        return [lst[-1].market_data for _, lst in sorted(self._by_key.items(), key=lambda kv: (kv[0][1], kv[0][0]))]

    def report(self) -> dict:
        st = self.status()
        return {
            "status": st.value,
            "unknown_policy": self.unknown_policy.value,
            "observations": len(self.observations),
            "unknown_availability_count": len(self.unknown),
            "unverifiable_records": [
                f"{o.key[0]}@{o.key[1].isoformat()}#r{o.revision}" for o in self.unknown
            ],
            "revised_keys": [f"{k[0]}@{k[1].isoformat()}" for k in self.revised_keys()],
            "ingestion_time_used_as_availability": any(
                o.basis is AvailabilityBasis.INGESTION_RECORDED for o in self.observations
            ),
            "fingerprint": self.fingerprint(),
            "clean_point_in_time_claim": st in (PitStatus.VERIFIED, PitStatus.VERIFIED_INGESTION_BASED),
        }


class PointInTimeReplay:
    """Drop-in for `HistoricalReplay` whose every read is gated by availability time."""

    def __init__(self, ledger: AvailabilityLedger) -> None:
        self._ledger = ledger
        known = [o for o in ledger.observations if o.available_at is not None]
        if not known:
            raise ResearchRunFailure(
                FailureCategory.CONTAMINATION,
                "no observation has known availability; point-in-time replay is UNVERIFIABLE",
            )
        self.instrument_ids = frozenset(o.key[0] for o in known)
        # a decision cycle exists at a bar timestamp once at least one bar of it is available
        self._cycle_ts = sorted({o.key[1] for o in known})
        self._cycle_avail = {}
        for o in known:
            cur = self._cycle_avail.get(o.key[1])
            self._cycle_avail[o.key[1]] = o.available_at if cur is None else min(cur, o.available_at)  # type: ignore[type-var]

    def require_instruments(self, instrument_ids: Iterable[str]) -> None:
        missing = sorted(set(instrument_ids) - self.instrument_ids)
        if missing:
            raise ResearchRunFailure(
                FailureCategory.MISSING_DATA,
                f"instruments present in the universe schedule have no available market data: {missing}",
                instruments=missing,
            )

    def decision_timestamps(self, start: datetime, end: datetime) -> list[datetime]:
        i = bisect_right(self._cycle_ts, end)
        return [t for t in self._cycle_ts[:i] if t >= start]

    def visible(self, as_of: datetime) -> list[MarketData]:
        return self._ledger.resolve(as_of)

    def bar_at(self, instrument_id: str, timestamp: datetime) -> MarketData | None:
        return self._ledger.resolve_one(instrument_id, timestamp, timestamp)

    def last_close_on_or_before(self, instrument_id: str, as_of: datetime) -> MarketData | None:
        best = None
        for md in self._ledger.resolve(as_of):
            if md.instrument_id == instrument_id:
                best = md
        return best
