"""Market-data adapter contract + engineering-only adapters (Slice 13 §4.1).

No network adapter ships in this slice: no provider was verified for data rights. `UnverifiedSourceAdapter`
fails closed. Replay/synthetic adapters label every observation REPLAY/SYNTHETIC so they can never
satisfy live-data-shadow acceptance.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Protocol

from data.live.observation import FeedEvent, LiveObservation
from markets.lane import DataProvenance, MarketLane


class SourceNotVerified(Exception):  # noqa: N818
    pass


class LiveMarketDataAdapter(Protocol):
    lane: MarketLane
    provider_id: str

    def poll(self) -> Iterable[LiveObservation | FeedEvent]: ...


class UnverifiedSourceAdapter:
    """Placeholder for a provider whose entitlement/rights were not verified. Never returns data."""

    def __init__(self, lane: MarketLane, provider_id: str):
        self.lane, self.provider_id = lane, provider_id

    def poll(self):
        raise SourceNotVerified(f"{self.provider_id}: market-data rights/entitlement not verified")


class ReplayAdapter:
    """Replays recorded items. Forces provenance to REPLAY or SYNTHETIC; LIVE is refused."""

    def __init__(self, lane: MarketLane, provider_id: str, items, provenance: DataProvenance):
        if provenance is DataProvenance.LIVE:
            raise ValueError("replay/synthetic adapters cannot emit LIVE provenance")
        self.lane, self.provider_id = lane, provider_id
        self._items, self._prov, self._done = list(items), provenance, False

    def poll(self):
        if self._done:
            return []
        self._done = True
        return [replace(i, provenance=self._prov) if isinstance(i, LiveObservation) else i
                for i in self._items]  # fmt: skip
