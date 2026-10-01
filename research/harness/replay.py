"""Deterministic historical replay over canonical MarketData (Slice 5, spec §8, §9).

Consumes ONLY `domain.models.market_data.MarketData`. It knows nothing about NSE
CSVs, provider field names or provider APIs.

Defined behaviours (docs/research-harness.md §Replay):

* Duplicate (instrument_id, timestamp) — even across different `source`s — FAILS the
  run (DUPLICATE_DATA). There is no silent "last one wins".
* Invalid records (not MarketData, non-UTC timestamps) FAIL the run (INVALID_DATA).
* An instrument in the universe with no records at all FAILS the run (MISSING_DATA).
* Non-trading days: decision cycles exist only at timestamps where at least one
  observation exists; days with no observations produce no cycle.
* A held instrument with no observation at a cycle: handled by the runner (fail
  closed unless `carry_forward_marks` is explicitly enabled). Nothing here ever
  forward-fills.
* `visible(t)` returns only records with timestamp <= t. This is the ONLY way the
  runner obtains data for feature building; future bars are structurally absent.
  `MarketData.ingestion_time` is pipeline provenance, NOT an availability time, and
  is deliberately not used to gate visibility (documented limitation).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from datetime import datetime

from domain.models.market_data import MarketData
from research.harness.failures import FailureCategory, ResearchRunFailure
from shared.time.clock import is_utc


class HistoricalReplay:
    def __init__(self, market_data: Iterable[MarketData]) -> None:
        records = list(market_data)
        if not records:
            raise ResearchRunFailure(FailureCategory.MISSING_DATA, "market data is empty")
        seen: dict[tuple[str, datetime], MarketData] = {}
        for r in records:
            if not isinstance(r, MarketData):
                raise ResearchRunFailure(
                    FailureCategory.INVALID_DATA,
                    f"replay accepts canonical MarketData only, got {type(r).__name__}",
                )
            if not is_utc(r.timestamp):
                raise ResearchRunFailure(
                    FailureCategory.INVALID_DATA,
                    f"MarketData timestamp for {r.instrument_id} is not UTC-aware",
                )
            key = (r.instrument_id, r.timestamp)
            if key in seen:
                raise ResearchRunFailure(
                    FailureCategory.DUPLICATE_DATA,
                    f"duplicate observation for {r.instrument_id} at {r.timestamp.isoformat()}",
                    instrument_id=r.instrument_id,
                    timestamp=r.timestamp.isoformat(),
                )
            seen[key] = r
        # Deterministic chronological order (ties broken by instrument id).
        self._records = sorted(seen.values(), key=lambda r: (r.timestamp, r.instrument_id))
        self._timestamps = [r.timestamp for r in self._records]
        self._by_key = seen
        self.instrument_ids = frozenset(r.instrument_id for r in self._records)

    def require_instruments(self, instrument_ids: Iterable[str]) -> None:
        missing = sorted(set(instrument_ids) - self.instrument_ids)
        if missing:
            raise ResearchRunFailure(
                FailureCategory.MISSING_DATA,
                f"instruments present in the universe schedule have no market data: {missing}",
                instruments=missing,
            )

    def decision_timestamps(self, start: datetime, end: datetime) -> list[datetime]:
        """Distinct observation timestamps within [start, end], ascending."""
        out: list[datetime] = []
        for ts in self._timestamps:
            if ts < start:
                continue
            if ts > end:
                break
            if not out or out[-1] != ts:
                out.append(ts)
        return out

    def visible(self, as_of: datetime) -> list[MarketData]:
        """All observations with timestamp <= as_of, chronologically ordered."""
        idx = bisect_right(self._timestamps, as_of)
        return self._records[:idx]

    def bar_at(self, instrument_id: str, timestamp: datetime) -> MarketData | None:
        return self._by_key.get((instrument_id, timestamp))

    def last_close_on_or_before(self, instrument_id: str, as_of: datetime) -> MarketData | None:
        idx = bisect_right(self._timestamps, as_of)
        for r in reversed(self._records[:idx]):
            if r.instrument_id == instrument_id:
                return r
        return None
