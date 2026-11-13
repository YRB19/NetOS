from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from markets.lane import MarketLane


class ExternalState(str, Enum):  # noqa: UP042
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    UNKNOWN = "UNKNOWN"  # submission outcome ambiguous: resolve via read-back, never blind retry
    ADAPTER_ERROR = "ADAPTER_ERROR"
    UNSUPPORTED = "UNSUPPORTED"


class IntegrationMode(str, Enum):  # noqa: UP042
    MOCK = "MOCK"  # NOT proof of external platform integration
    PAPER_REAL = "PAPER_REAL"


@dataclass(frozen=True)
class ApprovedIntent:
    """Frozen copy of an order intent ALREADY approved by NetOS risk + sizing. The platform cannot alter it."""

    lane: MarketLane
    instrument_id: str
    side: str
    quantity: int
    order_type: str
    internal_order_id: str
    internal_idempotency_key: str
    risk_decision_id: str
    decision_reference_price: float | None = None


def client_order_id(intent: ApprovedIntent, platform_id: str) -> str:
    """Deterministic, platform-scoped client id: a retry of the SAME intent reuses the SAME id."""
    h = hashlib.sha256(f"{platform_id}|{intent.internal_idempotency_key}".encode()).hexdigest()[:32]
    return f"nos-{h}"


@dataclass(frozen=True)
class ExternalFill:
    external_order_id: str
    quantity: int
    price: float
    fee: float
    currency: str


@dataclass(frozen=True)
class ExternalOrderStatus:
    external_order_id: str | None
    client_order_id: str
    state: ExternalState
    filled_quantity: int = 0
    reason: str = ""


class ExternalPaperAdapter(Protocol):
    platform_id: str
    mode: IntegrationMode
    lane: MarketLane
    endpoint: str

    def submit_order(self, intent: ApprovedIntent, client_id: str) -> ExternalOrderStatus: ...
    def get_order_by_client_id(self, client_id: str) -> ExternalOrderStatus | None: ...
    def get_fills(self, external_order_id: str) -> list[ExternalFill]: ...
