"""Broker-neutral adapter interface (Stage 3 §10) — Slice 6.

No credentials, tokens, endpoints or SDK types appear here. The only concrete
implementation shipped is the offline SimulatedBrokerAdapter (ADR-8).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from domain.models.enums import OrderState
from domain.models.order import StateTransitionRecord
from domain.models.order_request import Fill, OrderRequest
from domain.models.portfolio import Position
from shared.costs import CostEstimate
from shared.versioning.content_hash import hash_json_stable


class BrokerError(Exception):
    """Base class for broker-adapter failures (fail closed; never swallowed)."""


class BrokerRequestError(BrokerError):
    """The request is structurally invalid; no order was created."""


class CredentialsNotSupported(BrokerError):
    """The simulated broker refuses credentials: it must never receive any."""


class BrokerOperationNotSupported(BrokerError):
    pass


def order_id_for_idempotency_key(key: str) -> str:
    return "ord_" + hash_json_stable(key)[:24]


def broker_order_id_for_idempotency_key(key: str) -> str:
    return "SIM-" + hash_json_stable(["broker", key])[:20]


@dataclass(frozen=True)
class BrokerSession:
    adapter_id: str
    adapter_version: str
    simulated: bool


@dataclass(frozen=True)
class AccountState:
    cash_balance: Decimal
    margin_available: Decimal
    margin_used: Decimal


@dataclass(frozen=True)
class OrderStatus:
    broker_order_id: str
    order_id: str
    state: OrderState
    quantity: int
    filled_quantity: int
    remaining_quantity: int
    last_response: str
    state_history: tuple[StateTransitionRecord, ...]
    duplicate: bool = False


@dataclass(frozen=True)
class BrokerFillReport:
    """One broker-confirmed execution plus everything reconciliation needs."""

    fill: Fill
    charges: CostEstimate
    broker_order_id: str
    idempotency_key: str
    risk_decision_id: str
    state_after: OrderState
    adapter_id: str
    adapter_version: str


class BrokerAdapter(Protocol):
    def authenticate(self, credentials: object | None = None) -> BrokerSession: ...
    def get_account_state(self, session: BrokerSession) -> AccountState: ...
    def get_positions(self, session: BrokerSession) -> tuple[Position, ...]: ...
    def place_order(self, session: BrokerSession, request: OrderRequest) -> OrderStatus: ...
    def modify_order(self, session: BrokerSession, broker_order_id: str, changes: dict) -> OrderStatus: ...
    def cancel_order(self, session: BrokerSession, broker_order_id: str) -> OrderStatus: ...
    def get_order_status(self, session: BrokerSession, broker_order_id: str) -> OrderStatus: ...
    def find_order_by_client_key(self, session: BrokerSession, idempotency_key: str) -> OrderStatus | None: ...
    def get_fills(self, session: BrokerSession, broker_order_id: str | None = None) -> tuple[BrokerFillReport, ...]: ...
