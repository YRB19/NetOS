"""Explicit evaluation context for the Risk Engine (Slice 6).

Everything the engine needs beyond the CandidateTrade and its own RiskConfig arrives
here. Every field is OPTIONAL at construction on purpose: a missing field is not an
error to raise but a condition the engine must turn into a VETO (fail closed).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from domain.models.enums import Action
from domain.models.portfolio import PortfolioState
from risk_execution.risk_engine.config import KillSwitchState

PROTECTED_TARGETS = frozenset(
    {"risk_rules", "kill_switch", "operator_constraints", "execution_authority", "autonomy_level"}
)


@dataclass(frozen=True)
class PendingIntent:
    """An order already submitted but not yet fully filled (counts toward exposure)."""

    instrument_id: str
    side: Action
    quantity: int


@dataclass(frozen=True)
class ChangeRequest:
    """A request, arriving inside a research/strategy cycle, to alter a protected item (RR-9)."""

    target: str
    requester: str


@dataclass(frozen=True)
class RiskContext:
    evaluated_at: datetime | None = None
    portfolio: PortfolioState | None = None
    equity: Decimal | None = None
    peak_equity: Decimal | None = None
    reference_prices: Mapping[str, Decimal] | None = None
    pending_intents: tuple[PendingIntent, ...] = ()
    permitted_instrument_ids: frozenset[str] | None = None
    universe_version: str | None = None
    account_scope: str | None = None
    kill_switch: KillSwitchState | None = None
    drawdown_halt_latched: bool = False
    recent_order_timestamps: tuple[datetime, ...] | None = None
    snapshot_ids: Mapping[str, str] | None = None
    research_run_id: str | None = None
    config_version_id: str | None = None
    expected_risk_rule_version_id: str | None = None
    requested_changes: tuple[ChangeRequest, ...] = ()
