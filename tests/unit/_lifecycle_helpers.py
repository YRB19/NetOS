"""Shared fixtures for Slice 7 tests. SYNTHETIC; deterministic; offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from domain.models.enums import Action, FillType, RiskVerdict
from domain.models.order_request import Fill, OrderRequest, OrderType
from domain.models.risk_decision import RiskCheckResult, RiskDecision
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.broker.interface import order_id_for_idempotency_key
from risk_execution.order_lifecycle import BrokerEvent, EventKind, OrderLifecycleManager, event_from_fill_report
from risk_execution.reconciliation import LedgerView
from shared.versioning.identifiers import new_id
from tests.unit._pipeline_helpers import broker_config

T0 = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
A = "INE001X00001"
RRV = new_id()  # risk rule version id used by every test manager


def day(n: int) -> datetime:
    return T0 + timedelta(days=n)


def decision(qty: float = 100.0, verdict=RiskVerdict.APPROVE, rrv: str = RRV) -> RiskDecision:
    if verdict is RiskVerdict.APPROVE:
        return RiskDecision(new_id(), (RiskCheckResult("RR-1", True, "ok"),), verdict, rrv, approved_qty=qty)
    return RiskDecision(new_id(), (RiskCheckResult("RR-1", False, "no"),), verdict, rrv, reasons=("vetoed",))


def request_for(rd: RiskDecision, qty: float = 100.0, side=Action.BUY, key: str | None = None,
                otype=OrderType.MARKET, inst: str = A) -> OrderRequest:
    return OrderRequest(inst, side, qty, otype, rd.risk_decision_id, None, key or new_id())


class Rig:
    """A broker, a session, a lifecycle manager with an injected clock, and convenience wrappers."""

    def __init__(self, **broker_cfg) -> None:
        self.broker = SimulatedBrokerAdapter(broker_config(**broker_cfg))
        self.session = self.broker.authenticate()
        self.broker.set_simulated_time(T0)
        self.now = {"t": T0}
        self.mgr = OrderLifecycleManager(RRV, lambda: self.now["t"])
        self.opening = LedgerView(Decimal("1000000"), {})

    def at(self, t: datetime) -> None:
        self.now["t"] = t

    def submit(self, qty: float = 100.0, side=Action.BUY, key: str | None = None, **kw):
        rd = decision(max(qty, 1.0))
        req = request_for(rd, qty, side, key, **kw)
        return req, rd, self.mgr.submit(req, rd, self.broker, self.session)

    def advance(self, n: int, price: str = "50"):
        self.at(day(n))
        return self.broker.advance(day(n), {A: Decimal(price)})

    def fill_events(self, reports, ids=None):
        return [event_from_fill_report(r, None if ids is None else ids[i]) for i, r in enumerate(reports)]

    def broker_view(self) -> LedgerView:
        snap = self.broker.ledger_snapshot()
        return LedgerView(snap["cash"], snap["positions"])


def synthetic_fill(order_key: str, qty: float, price: float, ftype=FillType.PARTIAL, fid: str | None = None,
                   ts: datetime | None = None) -> Fill:
    return Fill(order_id_for_idempotency_key(order_key), qty, price, ts or day(1), ftype, fid or new_id())


def fill_event(key: str, fill: Fill, event_id: str | None = None) -> BrokerEvent:
    return BrokerEvent(EventKind.FILL, None, key, event_id=event_id, fill=fill)
