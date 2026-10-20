"""SimulatedBrokerAdapter — offline, deterministic, credential-free (ADR-8, Slice 6).

SIMULATION ASSUMPTIONS (explicit; NOT realistic market microstructure):
  * MARKET orders only. LIMIT orders and fractional quantities are REJECTED.
  * Fill price = the supplied bar OPEN of the first bar strictly AFTER acceptance
    ("NEXT_BAR_OPEN"), no slippage, no market impact, no queueing.
  * Fill size per bar: all remaining quantity (default), or — deterministically —
    max(1, floor(quantity * max_fill_fraction_per_bar)) when the fraction is < 1.
  * Charges per fill come from the shared India-equity Cost Model (the same schedule
    the research portfolio uses), so broker cash and portfolio cash reconcile exactly.
  * The broker keeps its OWN cash/position ledger (independent accounting) so the
    pipeline can reconcile against it.
  * Time is injected (`set_simulated_time`); no wall clock, no randomness, no network.

Lifecycle uses the existing domain Order state machine (no second lifecycle):
CANDIDATE -> APPROVED -> SUBMITTED -> ACKNOWLEDGED -> PARTIALLY_FILLED/FILLED, with
PARTIALLY_FILLED -> CANCELLED, REJECTED, and RECONCILIATION_REQUIRED. The existing
contract does not allow cancelling an unfilled ACKNOWLEDGED order; cancel_order on
one raises InvalidOrderTransition (the contract was deliberately not changed).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from domain.models.enums import Action, FillType, OrderState
from domain.models.order import Order
from domain.models.order_request import Fill, OrderRequest, OrderType
from domain.models.portfolio import Position
from risk_execution.broker.interface import (
    AccountState,
    BrokerFillReport,
    BrokerOperationNotSupported,
    BrokerRequestError,
    BrokerSession,
    CredentialsNotSupported,
    OrderStatus,
    broker_order_id_for_idempotency_key,
    order_id_for_idempotency_key,
)
from shared.costs import CostInputs, CostModel, TradeType, TransactionSide
from shared.versioning.content_hash import hash_json_stable

ADAPTER_ID = "simulated-broker"
ADAPTER_VERSION = "simulated-broker-v1"
FILL_ASSUMPTION = "FULL_OR_FIXED_FRACTION_AT_NEXT_BAR_OPEN_NO_SLIPPAGE"


@dataclass(frozen=True)
class SimulatedBrokerConfig:
    label: str
    initial_cash: Decimal
    cost_schedule_version: str
    max_fill_fraction_per_bar: Decimal = Decimal(1)

    def validate(self) -> list[str]:
        e: list[str] = []
        if not isinstance(self.label, str) or not self.label.strip():
            e.append("label must be non-empty")
        try:
            if Decimal(self.initial_cash) <= 0 or not Decimal(self.initial_cash).is_finite():
                e.append("initial_cash must be a positive finite decimal")
        except Exception:  # noqa: BLE001
            e.append("initial_cash invalid")
        if not isinstance(self.cost_schedule_version, str) or not self.cost_schedule_version:
            e.append("cost_schedule_version must be non-empty")
        try:
            f = Decimal(self.max_fill_fraction_per_bar)
            if not (Decimal(0) < f <= Decimal(1)):
                e.append("max_fill_fraction_per_bar must be in (0, 1]")
        except Exception:  # noqa: BLE001
            e.append("max_fill_fraction_per_bar invalid")
        return e

    def payload(self) -> dict:
        return {"label": self.label, "initial_cash": str(Decimal(self.initial_cash)),
                "cost_schedule_version": self.cost_schedule_version,
                "max_fill_fraction_per_bar": str(Decimal(self.max_fill_fraction_per_bar)),
                "fill_assumption": FILL_ASSUMPTION, "adapter_version": ADAPTER_VERSION}  # fmt: skip


@dataclass
class _BrokerOrder:
    request: OrderRequest
    order: Order
    seq: int
    accepted_at: datetime
    filled: int = 0
    fills: list[BrokerFillReport] = field(default_factory=list)

    @property
    def quantity(self) -> int:
        return int(self.request.quantity)


class SimulatedBrokerAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, config: SimulatedBrokerConfig, cost_model: CostModel | None = None) -> None:
        errs = config.validate()
        if errs:
            raise ValueError("invalid SimulatedBrokerConfig: " + "; ".join(errs))
        self.config = config
        self._cost = cost_model or CostModel()
        self._orders: dict[str, _BrokerOrder] = {}
        self._by_key: dict[str, str] = {}
        self._cash = Decimal(config.initial_cash)
        self._qty: dict[str, int] = {}
        self._cost_basis: dict[str, Decimal] = {}
        self._now: datetime | None = None
        self._seq = 0
        self.duplicate_submissions = 0
        self._faults: list[str] = []  # FAULT-INJECTION (tests only): one-shot place_order faults

    # ----------------------------------------------------------------- clock
    def set_simulated_time(self, ts: datetime) -> None:
        if ts.tzinfo is None:
            raise ValueError("simulated time must be timezone-aware")
        if self._now is not None and ts < self._now:
            raise ValueError("simulated time may not move backwards")
        self._now = ts

    def _time(self) -> datetime:
        if self._now is None:
            raise BrokerRequestError("simulated time not set (no wall-clock fallback by design)")
        return self._now

    # --------------------------------------------------------------- session
    def authenticate(self, credentials: object | None = None) -> BrokerSession:
        if credentials is not None:
            raise CredentialsNotSupported("the simulated broker accepts no credentials, ever")
        return BrokerSession(ADAPTER_ID, ADAPTER_VERSION, True)

    def _check(self, session: BrokerSession) -> None:
        if not isinstance(session, BrokerSession) or not session.simulated:
            raise BrokerRequestError("invalid or non-simulated session")

    # ---------------------------------------------------------------- queries
    def get_account_state(self, session: BrokerSession) -> AccountState:
        self._check(session)
        return AccountState(self._cash, self._cash, Decimal(0))

    def get_positions(self, session: BrokerSession) -> tuple[Position, ...]:
        self._check(session)
        return tuple(
            Position(i, float(q), float(self._cost_basis[i] / q))
            for i, q in sorted(self._qty.items()) if q > 0
        )  # fmt: skip

    def _status(self, bo: _BrokerOrder, duplicate: bool = False) -> OrderStatus:
        return OrderStatus(
            broker_order_id=bo.order.broker_order_id or "",
            order_id=bo.order.order_id,
            state=bo.order.state,
            quantity=bo.quantity,
            filled_quantity=bo.filled,
            remaining_quantity=bo.quantity - bo.filled,
            last_response=bo.order.last_broker_response or "",
            state_history=bo.order.state_history,
            duplicate=duplicate,
        )

    def _get(self, broker_order_id: str) -> _BrokerOrder:
        bo = self._orders.get(broker_order_id)
        if bo is None:
            raise BrokerRequestError(f"unknown broker_order_id {broker_order_id!r}")
        return bo

    def get_order_status(self, session: BrokerSession, broker_order_id: str) -> OrderStatus:
        self._check(session)
        return self._status(self._get(broker_order_id))

    def order_statuses(self, session: BrokerSession) -> dict[str, OrderStatus]:
        """Every order the broker holds, keyed by broker_order_id (reconciliation aid, Slice 7)."""
        self._check(session)
        return {bid: self._status(bo) for bid, bo in self._orders.items()}

    def get_fills(self, session: BrokerSession, broker_order_id: str | None = None):
        self._check(session)
        if broker_order_id is not None:
            return tuple(self._get(broker_order_id).fills)
        return tuple(f for bo in sorted(self._orders.values(), key=lambda b: b.seq) for f in bo.fills)

    # ----------------------------------------------------------------- orders
    def place_order(self, session: BrokerSession, request: OrderRequest) -> OrderStatus:
        self._check(session)
        if not isinstance(request, OrderRequest):
            raise BrokerRequestError("place_order requires an OrderRequest")
        now = self._time()
        fault = self._faults.pop(0) if self._faults else None
        if fault == "FAIL_BEFORE_ACCEPT":  # connection lost before the broker saw the request
            raise ConnectionError("simulated: connection lost before acceptance")
        existing = self._by_key.get(request.idempotency_key)
        if existing is not None:
            self.duplicate_submissions += 1
            return self._status(self._orders[existing], duplicate=True)

        self._seq += 1
        order = Order(
            order_request_id=request.idempotency_key,
            order_id=order_id_for_idempotency_key(request.idempotency_key),
        )
        bid = broker_order_id_for_idempotency_key(request.idempotency_key)
        order.set_broker_order_id(bid)
        bo = _BrokerOrder(request, order, self._seq, now)
        self._orders[bid] = bo
        self._by_key[request.idempotency_key] = bid
        order.transition_to(OrderState.APPROVED, at=now,
                            detail=f"risk_decision_id={request.risk_decision_id}")  # fmt: skip
        order.transition_to(OrderState.SUBMITTED, at=now, detail="received by simulated broker")
        reason = self._invalid_reason(request)
        if reason:
            order.last_broker_response = reason
            order.transition_to(OrderState.REJECTED, at=now, detail=reason)
        else:
            order.last_broker_response = "ACKNOWLEDGED"
            order.transition_to(OrderState.ACKNOWLEDGED, at=now, detail="accepted")
        if fault == "FAIL_AFTER_ACCEPT":  # broker accepted, but the caller never receives the response
            raise TimeoutError("simulated: response lost after acceptance")
        return self._status(bo)

    @staticmethod
    def _invalid_reason(r: OrderRequest) -> str | None:
        if r.order_type is not OrderType.MARKET:
            return f"unsupported order type {r.order_type.value} (simulator supports MARKET only)"
        if float(r.quantity) != int(r.quantity):
            return "fractional quantity unsupported"
        return None

    def modify_order(self, session: BrokerSession, broker_order_id: str, changes: dict) -> OrderStatus:
        self._check(session)
        raise BrokerOperationNotSupported("modify_order is out of scope for the Slice 6 simulator")

    def cancel_order(self, session: BrokerSession, broker_order_id: str) -> OrderStatus:
        self._check(session)
        bo = self._get(broker_order_id)
        bo.order.last_broker_response = "CANCELLED_BY_REQUEST"
        # raises InvalidOrderTransition unless PARTIALLY_FILLED (existing state-machine contract)
        bo.order.transition_to(OrderState.CANCELLED, at=self._time(), detail="cancel requested")
        return self._status(bo)

    def inject_fault(self, kind: str) -> None:
        """FAULT-INJECTION HOOK (tests only): next place_order fails as FAIL_BEFORE_ACCEPT | FAIL_AFTER_ACCEPT."""
        if kind not in ("FAIL_BEFORE_ACCEPT", "FAIL_AFTER_ACCEPT"):
            raise ValueError(kind)
        self._faults.append(kind)

    def find_order_by_client_key(self, session: BrokerSession, idempotency_key: str) -> OrderStatus | None:
        """Authoritative lookup by client order id (None = the broker never received it). Slice 7."""
        self._check(session)
        bid = self._by_key.get(idempotency_key)
        return None if bid is None else self._status(self._orders[bid])

    def inject_ambiguous_response(self, broker_order_id: str, detail: str = "ambiguous") -> OrderStatus:
        """FAULT-INJECTION HOOK (tests only): force RECONCILIATION_REQUIRED."""
        bo = self._get(broker_order_id)
        bo.order.last_broker_response = detail
        bo.order.transition_to(OrderState.RECONCILIATION_REQUIRED, at=self._time(), detail=detail)
        return self._status(bo)

    # ------------------------------------------------------------- execution
    def advance(
        self, timestamp: datetime, open_prices: Mapping[str, Decimal]
    ) -> tuple[BrokerFillReport, ...]:
        """Execute resting orders accepted strictly before `timestamp` at the supplied opens."""
        self.set_simulated_time(timestamp)
        out: list[BrokerFillReport] = []
        live = [
            bo for bo in self._orders.values()
            if bo.order.state in (OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED)
            and bo.accepted_at < timestamp and bo.request.instrument_id in open_prices
        ]  # fmt: skip
        live.sort(key=lambda b: (b.request.side is not Action.SELL, b.seq))
        frac = Decimal(self.config.max_fill_fraction_per_bar)
        for bo in live:
            r = bo.request
            price = Decimal(open_prices[r.instrument_id])
            remaining = bo.quantity - bo.filled
            q = remaining if frac == 1 else min(remaining, max(1, int(Decimal(bo.quantity) * frac)))
            side = TransactionSide.BUY if r.side is Action.BUY else TransactionSide.SELL
            est = self._cost.estimate(
                CostInputs(side, TradeType.DELIVERY, q, price, self.config.cost_schedule_version)
            )
            turnover = Decimal(q) * price
            if r.side is Action.BUY and turnover + est.total_cost > self._cash:
                self._stop(bo, timestamp, "insufficient cash at fill")
                continue
            if r.side is Action.SELL and q > self._qty.get(r.instrument_id, 0):
                self._stop(bo, timestamp, "insufficient position at fill")
                continue
            self._book(r, q, price, turnover, est.total_cost)
            bo.filled += q
            done = bo.filled >= bo.quantity
            fill = Fill(
                order_id=bo.order.order_id,
                quantity=float(q),
                price=float(price),
                timestamp=timestamp,
                fill_type=FillType.FULL if done else FillType.PARTIAL,
                fill_id="fill_" + hash_json_stable([bo.order.order_id, timestamp.isoformat(), bo.filled])[:24],
            )
            new_state = OrderState.FILLED if done else OrderState.PARTIALLY_FILLED
            if bo.order.state is not new_state:
                bo.order.transition_to(new_state, at=timestamp, detail=f"filled {bo.filled}/{bo.quantity}")
            bo.order.last_broker_response = new_state.value
            rep = BrokerFillReport(fill, est, bo.order.broker_order_id or "", r.idempotency_key,
                                   r.risk_decision_id, new_state, ADAPTER_ID, ADAPTER_VERSION)  # fmt: skip
            bo.fills.append(rep)
            out.append(rep)
        return tuple(out)

    def _stop(self, bo: _BrokerOrder, ts: datetime, why: str) -> None:
        bo.order.last_broker_response = why
        if bo.order.state is OrderState.ACKNOWLEDGED:
            bo.order.transition_to(OrderState.REJECTED, at=ts, detail=why)
        else:  # partially filled: the unfillable remainder is cancelled
            bo.order.transition_to(OrderState.CANCELLED, at=ts, detail=why + " (remainder cancelled)")

    def _book(self, r: OrderRequest, q: int, price: Decimal, turnover: Decimal, cost: Decimal) -> None:
        i = r.instrument_id
        if r.side is Action.BUY:
            self._cash -= turnover + cost
            self._qty[i] = self._qty.get(i, 0) + q
            self._cost_basis[i] = self._cost_basis.get(i, Decimal(0)) + turnover
        else:
            self._cash += turnover - cost
            old = self._qty[i]
            self._cost_basis[i] = self._cost_basis[i] * Decimal(old - q) / Decimal(old)
            self._qty[i] = old - q
            if self._qty[i] == 0:
                del self._qty[i]
                self._cost_basis.pop(i, None)

    # ------------------------------------------------------ reconciliation aid
    def ledger_snapshot(self) -> dict:
        return {"cash": self._cash, "positions": dict(sorted(self._qty.items()))}
