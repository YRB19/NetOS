"""Independent-ledger reconciliation (Slice 6, FR-4, Stage 3 §3.4/§9).

The research portfolio (system belief) and the simulated broker's own ledger
(broker truth) are maintained independently. They must agree after every settlement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from risk_execution.reconciliation import compare_cash_positions


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    mismatches: tuple[str, ...]
    portfolio_cash: Decimal
    broker_cash: Decimal
    portfolio_positions: Mapping[str, int]
    broker_positions: Mapping[str, int]


def reconcile(
    portfolio_cash: Decimal,
    portfolio_positions: Mapping[str, int],
    broker_cash: Decimal,
    broker_positions: Mapping[str, int],
) -> ReconciliationResult:
    mism = compare_cash_positions(portfolio_cash, portfolio_positions, broker_cash, broker_positions)
    return ReconciliationResult(not mism, tuple(mism), portfolio_cash, broker_cash,
                                dict(portfolio_positions), dict(broker_positions))  # fmt: skip
