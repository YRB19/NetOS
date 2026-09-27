"""
Domain contracts for the Cost Model (Slice 4).

These are plain, immutable data structures with no I/O and no dependency on
broker, strategy, LLM, or research code, per Stage 3 §6/§19/§20.

Monetary values use ``decimal.Decimal`` throughout. Binary floating point is
never used for money in this module (Stage 3 §14/§15 rounding/monetary
representation requirements).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum


class TransactionSide(Enum):
    """Which side of a trade a cost calculation applies to."""

    BUY = "BUY"
    SELL = "SELL"


class TradeType(Enum):
    """Delivery (positional) vs. intraday, per Stage 1 TR-5's distinction.

    Several Indian-equity cost components (STT, stamp duty, brokerage) differ
    materially between these two, so the distinction is a first-class input
    field rather than something inferred later.
    """

    DELIVERY = "DELIVERY"
    INTRADAY = "INTRADAY"


def _to_decimal(value: Decimal | int | float | str, field_name: str) -> Decimal:
    """Coerce an incoming numeric value to Decimal, rejecting NaN/Infinity.

    Floats are accepted for caller convenience but are converted via ``str()``
    rather than passed directly to ``Decimal()``, to avoid importing binary
    floating-point representation error into a monetary value.
    """
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, float):
        candidate = Decimal(str(value))
    else:
        try:
            candidate = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} is not a valid decimal number: {value!r}") from exc

    if not candidate.is_finite():
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return candidate


@dataclass(frozen=True)
class CostInputs:
    """Canonical, immutable input to a single cost calculation.

    Deliberately NOT an ``OrderRequest`` or any broker/execution object
    (Stage 3 §4) — this keeps the Cost Model callable from Research/backtest
    code that has no broker, order, or execution context at all.
    """

    side: TransactionSide
    trade_type: TradeType
    quantity: int
    price: Decimal
    schedule_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.side, TransactionSide):
            raise ValueError(f"side must be a TransactionSide, got {self.side!r}")
        if not isinstance(self.trade_type, TradeType):
            raise ValueError(f"trade_type must be a TradeType, got {self.trade_type!r}")

        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool):
            raise ValueError(f"quantity must be an int, got {self.quantity!r}")
        if self.quantity < 0:
            raise ValueError(f"quantity must be non-negative, got {self.quantity}")

        price = _to_decimal(self.price, "price")
        object.__setattr__(self, "price", price)
        if price < 0:
            raise ValueError(f"price must be non-negative, got {price}")
        if self.quantity > 0 and price <= 0:
            raise ValueError("price must be positive when quantity > 0")

        if not self.schedule_version or not isinstance(self.schedule_version, str):
            raise ValueError(
                f"schedule_version must be a non-empty string, got {self.schedule_version!r}"
            )

    @property
    def gross_turnover(self) -> Decimal:
        """Quantity * price. Zero for a zero-quantity (no-op) transaction."""
        return Decimal(self.quantity) * self.price

    @property
    def is_zero_value(self) -> bool:
        """A zero-quantity transaction — see Stage 3 §4's explicit-behavior requirement."""
        return self.quantity == 0


@dataclass(frozen=True)
class CostEstimate:
    """Immutable output of a single cost calculation.

    Every component is always present (never omitted), and is explicitly
    zero when not applicable to this side/trade_type combination, per
    Stage 3 §5's "represent that explicitly as zero rather than silently
    omitting it" instruction.
    """

    schedule_version: str
    side: TransactionSide
    trade_type: TradeType
    gross_turnover: Decimal

    brokerage: Decimal
    stt: Decimal
    exchange_txn_charges: Decimal
    sebi_charges: Decimal
    gst: Decimal
    stamp_duty: Decimal

    total_cost: Decimal

    # Free-form provenance/assumption notes carried from the schedule that
    # produced this estimate, so a reader of the estimate alone (without
    # cross-referencing the schedule separately) can see what was assumed.
    schedule_notes: Mapping[str, str] = field(default_factory=dict)

    def component_total(self) -> Decimal:
        """Recompute total from components — used to prove reconstructability."""
        return (
            self.brokerage
            + self.stt
            + self.exchange_txn_charges
            + self.sebi_charges
            + self.gst
            + self.stamp_duty
        )

    def cost_pct_of_turnover(self) -> Decimal:
        """Total cost as a percentage of gross turnover.

        Explicitly zero when turnover is zero (Stage 3 §17's requirement to
        define zero-turnover behavior explicitly), never a division error.
        """
        if self.gross_turnover == 0:
            return Decimal("0")
        return (self.total_cost / self.gross_turnover) * Decimal("100")
