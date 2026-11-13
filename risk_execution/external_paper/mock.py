"""Mock external paper platform. LABELLED MOCK: exercising the contract is not platform integration.

Has its OWN order ids, fills, prices and fees, deliberately different from the internal simulator's."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from markets.lane import MarketLane
from risk_execution.external_paper.contract import (
    ApprovedIntent, ExternalFill, ExternalOrderStatus, ExternalState, IntegrationMode,
)  # fmt: skip


class Fault(str, Enum):  # noqa: UP042
    NONE = "NONE"
    REJECT = "REJECT"
    UNSUPPORTED_SYMBOL = "UNSUPPORTED_SYMBOL"
    TIMEOUT_ORDER_CREATED = "TIMEOUT_ORDER_CREATED"  # response lost but order exists
    TIMEOUT_NO_ORDER = "TIMEOUT_NO_ORDER"  # response lost and order never created
    OUTAGE = "OUTAGE"
    PARTIAL = "PARTIAL"


@dataclass
class MockExternalPaperAdapter:
    lane: MarketLane
    platform_id: str = "MOCK_PAPER_PLATFORM"
    endpoint: str = "https://mock-paper.invalid"
    mode: IntegrationMode = IntegrationMode.MOCK
    fill_price_offset_bps: float = 5.0  # platform's OWN fill assumption (differs from internal on purpose)
    fee_per_order: float = 0.0
    fault: Fault = Fault.NONE
    supported: frozenset[str] | None = None
    _orders: dict = field(default_factory=dict)
    _fills: dict = field(default_factory=dict)
    _n: int = 0
    submit_calls: int = 0

    def submit_order(self, intent: ApprovedIntent, client_id: str) -> ExternalOrderStatus:
        self.submit_calls += 1
        if self.fault is Fault.OUTAGE:
            raise ConnectionError("mock platform outage")
        if self.supported is not None and intent.instrument_id not in self.supported:
            return ExternalOrderStatus(None, client_id, ExternalState.UNSUPPORTED, reason="unsupported symbol")
        if self.fault is Fault.REJECT:
            return ExternalOrderStatus(None, client_id, ExternalState.REJECTED, reason="mock rejection")
        if client_id in self._orders:  # platform-side idempotency of the mock
            return self._orders[client_id]
        self._n += 1
        ext_id = f"mockext-{self._n:06d}"
        px = intent.decision_reference_price or 0.0
        sgn = 1 if intent.side == "BUY" else -1
        price = round(px * (1 + sgn * self.fill_price_offset_bps / 1e4), 6) if px else 0.0
        qty = intent.quantity // 2 if self.fault is Fault.PARTIAL else intent.quantity
        state = ExternalState.PARTIALLY_FILLED if self.fault is Fault.PARTIAL else ExternalState.FILLED
        st = ExternalOrderStatus(ext_id, client_id, state, qty)
        self._orders[client_id] = st
        self._fills[ext_id] = [ExternalFill(ext_id, qty, price, self.fee_per_order, "MOCK")]
        if self.fault is Fault.TIMEOUT_ORDER_CREATED:
            raise TimeoutError("mock timeout after order creation")
        if self.fault is Fault.TIMEOUT_NO_ORDER:
            del self._orders[client_id]
            del self._fills[ext_id]
            raise TimeoutError("mock timeout; order never created")
        return st

    def get_order_by_client_id(self, client_id: str):
        if self.fault is Fault.OUTAGE:
            raise ConnectionError("mock platform outage")
        return self._orders.get(client_id)

    def get_fills(self, external_order_id: str):
        return list(self._fills.get(external_order_id, []))
