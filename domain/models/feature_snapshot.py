"""FeatureSnapshot (Stage 3 §2, §3.1) — the exact input Plane 2 saw.

Immutable, versioned by feature-set version. This is what makes every
decision fully reconstructable (FR-5) from a single referenced object,
and what keeps Plane 2 stateless with respect to governance (Stage 3 §3.1)
— Plane 2 receives exactly one FeatureSnapshot per cycle and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from domain.models._validators import require_aware_utc, require_non_empty_str, require_uuid_like
from shared.time.clock import is_utc
from shared.versioning.identifiers import new_id


@dataclass(frozen=True)
class MarketDataRef:
    """A pointer to the exact MarketData record(s) that fed this snapshot,
    by natural key, so the snapshot never needs to embed the raw record."""

    instrument_id: str
    timestamp: datetime
    source: str

    def __post_init__(self) -> None:
        if not is_utc(self.timestamp):
            raise ValueError("MarketDataRef.timestamp must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    instrument_id: str
    decision_timestamp: datetime
    feature_values: MappingProxyType[str, float]
    feature_set_version: str
    source_market_data_ids: tuple[str, ...] = field(default_factory=tuple)
    snapshot_id: str = field(default_factory=new_id)
    data_snapshot_version: str = ""
    incomplete: bool = False
    missing_fields: tuple[str, ...] = field(default_factory=tuple)

    universe_version: str = ""
    is_permitted: bool = False
    reference_price: float | None = None
    source_refs: tuple[MarketDataRef, ...] = field(default_factory=tuple)

    @property
    def feature_set_id(self) -> str:
        return self.feature_set_version

    @property
    def market_data_snapshot_version(self) -> str:
        return self.data_snapshot_version

    @property
    def values(self):
        return self.feature_values

    @property
    def is_complete(self) -> bool:
        return not self.incomplete and self.is_permitted and self.reference_price is not None

    def __post_init__(self) -> None:
        if self.reference_price is not None and self.reference_price <= 0:
            raise ValueError("reference_price must be positive")
        require_non_empty_str(self.instrument_id, "instrument_id")
        object.__setattr__(
            self,
            "decision_timestamp",
            require_aware_utc(self.decision_timestamp, "decision_timestamp"),
        )
        require_uuid_like(self.snapshot_id, "snapshot_id")
        require_non_empty_str(self.feature_set_version, "feature_set_version")

        object.__setattr__(self, "feature_values", MappingProxyType(dict(self.feature_values)))
        object.__setattr__(self, "source_refs", tuple(self.source_refs))

        if self.incomplete and not self.missing_fields:
            raise ValueError(
                "incomplete=True requires at least one entry in missing_fields "
                "(SF-1: a data gap must be attributable to specific fields, not "
                "an unexplained flag)."
            )
        if not self.incomplete and self.missing_fields:
            raise ValueError(
                "missing_fields must be empty when incomplete=False — a snapshot "
                "cannot simultaneously claim to be complete and list gaps."
            )

    def value(self, feature_name: str) -> float | None:
        return self.feature_values.get(feature_name)
