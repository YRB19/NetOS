"""MarketData domain model — canonical, normalized market observation.

Per Stage 3 §2: "One normalized market observation. instrument_id, timestamp, OHLCV, source,
ingestion_time. Immutable once written (corrections are new records). Identifiers:
(instrument_id, timestamp, source). Version refs: data snapshot version."

This is the ONLY market-data shape any downstream component (features, strategies, the
research harness) may consume. No adapter or Plane 2 implementation may hold its own parallel
representation (Stage 2 §7's "data flow principle").
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class MarketData:
    instrument_id: str  # canonical Instrument.isin
    timestamp: datetime  # UTC-aware; the moment this observation applies to (e.g. a trading day)
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
    ingestion_time: datetime  # UTC-aware; when our pipeline produced this canonical record
    data_snapshot_version: str
    adjusted: bool = False  # True if corporate-action-adjusted; False = as-traded
    raw_ref: str | None = None  # RawMarketObservation.raw_id this was derived from, if any

    def __post_init__(self) -> None:
        if not self.instrument_id or not self.instrument_id.strip():
            raise ValueError("MarketData.instrument_id must be a non-empty string.")
        if not self.source or not self.source.strip():
            raise ValueError("MarketData.source must be a non-empty string.")
        if not self.data_snapshot_version or not self.data_snapshot_version.strip():
            raise ValueError("MarketData.data_snapshot_version must be a non-empty string.")

        for name in ("timestamp", "ingestion_time"):
            value = getattr(self, name)
            if value.tzinfo is None:
                raise ValueError(f"MarketData.{name} must be timezone-aware (UTC).")
            if value.utcoffset() != UTC.utcoffset(None):
                raise ValueError(
                    f"MarketData.{name} must be stored in UTC, got offset {value.utcoffset()}."
                )

        for name in ("open", "high", "low", "close"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"MarketData.{name} must be numeric, got {type(value).__name__}.")
            if math.isnan(value) or math.isinf(value):
                raise ValueError(f"MarketData.{name} must be a finite number, got {value!r}.")
            if value <= 0:
                raise ValueError(f"MarketData.{name} must be > 0, got {value!r}.")

        if not isinstance(self.volume, int) or isinstance(self.volume, bool):
            raise ValueError(
                f"MarketData.volume must be an integer, got {type(self.volume).__name__}."
            )
        if self.volume < 0:
            raise ValueError(f"MarketData.volume must be >= 0, got {self.volume!r}.")

        # OHLC consistency (documented rule — see docs/data-ingestion.md "Numerical sanity"):
        #   high must be >= max(open, close, low)
        #   low  must be <= min(open, close, high)
        top = max(self.open, self.close, self.low)
        bottom = min(self.open, self.close, self.high)
        if self.high < top:
            raise ValueError(
                f"MarketData OHLC inconsistency: high={self.high} < max(open,close,low)={top}."
            )
        if self.low > bottom:
            raise ValueError(
                f"MarketData OHLC inconsistency: low={self.low} > min(open,close,high)={bottom}."
            )

    @property
    def identity_key(self) -> tuple[str, datetime, str]:
        """Canonical identity per Stage 3 §2: (instrument_id, timestamp, source).

        Used by the normalization layer's duplicate-detection logic (docs/data-ingestion.md).
        """
        return (self.instrument_id, self.timestamp, self.source)

    @property
    def record_key(self) -> tuple[str, datetime, str]:
        return self.identity_key
