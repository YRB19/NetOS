# ruff: noqa: UP042
# Keep existing Enum string/serialization semantics across slices.
"""OrderRequest / Fill (Stage 3 §2) — Plane 3's request to the broker, and a
broker-confirmed execution event.

OrderRequest is immutable once submitted (Stage 3 §2). Note this is the
*only* place in the domain model a real, authoritative order quantity
exists — deliberately downstream of CandidateTrade's merely-a-hint
`size_hint` (see candidate_trade.py's docstring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from domain.models._validators import (
    require_aware_utc,
    require_non_empty_str,
    require_positive,
    require_uuid_like,
)
from domain.models.enums import Action, FillType
from shared.versioning.identifiers import new_id


class OrderType(str, Enum):
    """Kept intentionally minimal for v1; see Stage 1 REG-5 (market/IOC review)."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    instrument_id: str
    side: Action  # BUY or SELL only — HOLD is not a valid order side
    quantity: float  # the ONE authoritative quantity in the whole domain model
    order_type: OrderType
    risk_decision_id: str  # FK -> RiskDecision
    limit_price: float | None = None
    idempotency_key: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        require_non_empty_str(self.instrument_id, "instrument_id")
        if self.side not in (Action.BUY, Action.SELL):
            raise ValueError(
                f"OrderRequest.side must be BUY or SELL, got: {self.side!r} "
                "(HOLD never produces an order request)."
            )
        require_positive(self.quantity, "quantity")
        if not isinstance(self.order_type, OrderType):
            raise ValueError(f"order_type must be an OrderType, got: {self.order_type!r}")
        require_uuid_like(self.risk_decision_id, "risk_decision_id")
        require_uuid_like(self.idempotency_key, "idempotency_key")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("order_type=LIMIT requires a limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("order_type=MARKET must not carry a limit_price")
        if self.limit_price is not None:
            require_positive(self.limit_price, "limit_price")


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: str  # FK -> Order.order_id (internal id, not broker_order_id)
    quantity: float
    price: float
    timestamp: datetime
    fill_type: FillType
    fill_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        require_uuid_like(self.order_id, "order_id")
        require_positive(self.quantity, "quantity")
        require_positive(self.price, "price")
        object.__setattr__(self, "timestamp", require_aware_utc(self.timestamp, "timestamp"))
        if not isinstance(self.fill_type, FillType):
            raise ValueError(f"fill_type must be a FillType, got: {self.fill_type!r}")
        require_uuid_like(self.fill_id, "fill_id")
