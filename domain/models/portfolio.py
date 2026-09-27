"""Position / PortfolioState (Stage 3 §2) — FR-4's "track positions at all times."

PortfolioState is append-only: FR-4's "at all times" requirement is
satisfied by always being able to read the latest reconciled record plus
its full history, never by mutating a single row (Stage 3 §3.4). Position
is "derived/recomputed, not directly edited" — i.e. also a plain immutable
snapshot, never mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.models._validators import require_aware_utc, require_non_empty_str
from domain.models.enums import PortfolioStateSource, PositionSide


@dataclass(frozen=True, slots=True)
class Position:
    instrument_id: str
    quantity: float
    avg_cost: float
    side: PositionSide = PositionSide.LONG
    as_of_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        require_non_empty_str(self.instrument_id, "instrument_id")
        if not isinstance(self.side, PositionSide):
            raise ValueError(f"side must be a PositionSide, got: {self.side!r}")
        if self.side is PositionSide.LONG and self.quantity < 0:
            raise ValueError(
                f"a LONG position cannot have negative quantity, got: {self.quantity!r} "
                "(no shorting is modeled in v1 — Stage 3 §2)."
            )
        if self.avg_cost < 0:
            raise ValueError(f"avg_cost cannot be negative, got: {self.avg_cost!r}")
        if self.as_of_timestamp is not None:
            object.__setattr__(
                self, "as_of_timestamp", require_aware_utc(self.as_of_timestamp, "as_of_timestamp")
            )


@dataclass(frozen=True, slots=True)
class PortfolioState:
    as_of_timestamp: datetime
    positions: tuple[Position, ...]
    cash_balance: float
    source: PortfolioStateSource
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "as_of_timestamp", require_aware_utc(self.as_of_timestamp, "as_of_timestamp")
        )
        if not isinstance(self.source, PortfolioStateSource):
            raise ValueError(f"source must be a PortfolioStateSource, got: {self.source!r}")
        if not isinstance(self.positions, tuple) or not all(
            isinstance(p, Position) for p in self.positions
        ):
            raise ValueError("positions must be a tuple of Position instances")
        if self.cash_balance < 0:
            raise ValueError(
                f"cash_balance cannot be negative in this model, got: {self.cash_balance!r} "
                "(margin/leverage is a separate, explicitly-gated concept — RR-2)."
            )
        instrument_ids = [p.instrument_id for p in self.positions]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("positions must not contain duplicate instrument_ids")

    def identity_key(self) -> tuple[datetime, PortfolioStateSource]:
        return (self.as_of_timestamp, self.source)

    def position_for(self, instrument_id: str) -> Position | None:
        for p in self.positions:
            if p.instrument_id == instrument_id:
                return p
        return None
