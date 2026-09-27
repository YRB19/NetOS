"""Instrument (Stage 3 §2) — a tradable equity.

`universe_member` is the one mutable-in-spirit field (Plane 0 can change
universe membership, per TR-1/TR-7), but per Stage 3's own note ("Membership
flag only, via Plane 0") the *object* itself is not mutated in place —
a universe-membership change produces a new Instrument snapshot. This
matches the append-only-versioning discipline used everywhere else in the
system and avoids a special-cased "one mutable field" exception.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from domain.models._validators import require_non_empty_str
from domain.models.enums import Segment


@dataclass(frozen=True, slots=True)
class Instrument:
    isin: str  # canonical identifier
    symbol: str
    exchange: str
    lot_size: int = 1
    segment: Segment = Segment.EQUITY
    universe_member: bool = False
    universe_config_version: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_str(self.isin, "isin")
        require_non_empty_str(self.symbol, "symbol")
        require_non_empty_str(self.exchange, "exchange")
        if not isinstance(self.lot_size, int) or self.lot_size <= 0:
            raise ValueError(f"lot_size must be a positive int, got: {self.lot_size!r}")
        if self.exchange not in {"NSE", "BSE"}:
            raise ValueError("exchange must be NSE or BSE")
        if self.segment == "EQUITY":
            object.__setattr__(self, "segment", Segment.EQUITY)
        if not isinstance(self.segment, Segment):
            raise ValueError(f"segment must be a Segment, got: {self.segment!r}")
        if self.universe_member and not self.universe_config_version:
            raise ValueError(
                "universe_member=True requires a universe_config_version "
                "(TR-1: universe membership must be attributable to a specific "
                "operator configuration, not an unversioned flag)."
            )

    @property
    def working_id(self) -> str:
        """The (symbol, exchange) working identifier, distinct from the canonical ISIN."""
        return f"{self.exchange}:{self.symbol}"

    def with_universe_membership(self, member: bool, config_version: str) -> Instrument:
        """Return a new Instrument snapshot reflecting a Plane-0 universe change."""
        return replace(
            self,
            universe_member=member,
            universe_config_version=config_version if member else self.universe_config_version,
        )

    @property
    def canonical_id(self) -> str:
        return self.isin

    @property
    def instrument_id(self) -> str:
        return self.isin
