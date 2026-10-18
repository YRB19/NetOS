"""Feature-builder protocol and the Tier-1 context builder wrapper (Slice 6)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Protocol

from data.features.context_builder import (
    DEFAULT_STALENESS_THRESHOLD,
    TIER1_CONTEXT_FEATURE_SET_ID,
    build_feature_snapshots,
)
from data.features.universe import PermittedUniverse
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.market_data import MarketData


class FeatureBuilder(Protocol):
    feature_set_id: str

    def identity(self) -> dict: ...

    def build(
        self,
        visible: list[MarketData],
        universe: PermittedUniverse,
        as_of: datetime,
        *,
        market_data_snapshot_version: str,
        staleness_threshold: timedelta = DEFAULT_STALENESS_THRESHOLD,
        instrument_ids: Iterable[str] | None = None,
    ) -> list[FeatureSnapshot]: ...


class ContextFeatureBuilder:
    """Tier-1 style context snapshots (price/staleness/universe only)."""

    def __init__(self, feature_set_id: str = TIER1_CONTEXT_FEATURE_SET_ID) -> None:
        self.feature_set_id = feature_set_id

    def identity(self) -> dict:
        return {"builder": "ContextFeatureBuilder", "feature_set_id": self.feature_set_id}

    def build(self, visible, universe, as_of, *, market_data_snapshot_version,
              staleness_threshold=DEFAULT_STALENESS_THRESHOLD, instrument_ids=None):  # noqa: ANN001
        return build_feature_snapshots(
            visible, universe, as_of,
            market_data_snapshot_version=market_data_snapshot_version,
            feature_set_id=self.feature_set_id,
            staleness_threshold=staleness_threshold,
            instrument_ids=instrument_ids,
        )  # fmt: skip
