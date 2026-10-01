"""Basic deterministic accounting metrics (Slice 5, spec §20).

Only what the core harness needs. No Sharpe/Sortino/alpha/beta/PBO. All figures are
NET of transaction costs, and equity is mark-to-market at the last decision close:
open positions are NOT liquidated, so exit costs are not deducted (documented
limitation). Returned Decimals are quantised so output is byte-stable.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from research.harness.portfolio import ResearchPortfolio

METRICS_BASIS = "NET_OF_TRANSACTION_COSTS__MARK_TO_MARKET__UNLIQUIDATED"
_MONEY = Decimal("0.01")
_RATIO = Decimal("0.00000001")


def compute_metrics(
    portfolio: ResearchPortfolio,
    final_marks: dict[str, Decimal],
    *,
    rejected_orders: int,
    unexecuted_orders: int,
    decision_cycles: int,
) -> dict:
    initial = portfolio.initial_capital
    final_equity = portfolio.equity(final_marks)
    net_pnl = final_equity - initial
    total_costs = portfolio.cumulative_costs
    gross_pnl = net_pnl + total_costs  # P&L before transaction costs
    return {
        "basis": METRICS_BASIS,
        "initial_capital": initial.quantize(_MONEY, ROUND_HALF_UP),
        "final_equity": final_equity.quantize(_MONEY, ROUND_HALF_UP),
        "net_pnl": net_pnl.quantize(_MONEY, ROUND_HALF_UP),
        "gross_pnl": gross_pnl.quantize(_MONEY, ROUND_HALF_UP),
        "total_transaction_costs": total_costs.quantize(_MONEY, ROUND_HALF_UP),
        "total_return": (net_pnl / initial).quantize(_RATIO, ROUND_HALF_UP),
        "number_of_transactions": portfolio.transaction_count,
        "turnover": portfolio.cumulative_turnover.quantize(_MONEY, ROUND_HALF_UP),
        "turnover_to_initial_capital": (portfolio.cumulative_turnover / initial).quantize(
            _RATIO, ROUND_HALF_UP
        ),
        "realized_pnl_gross": portfolio.realized_pnl_gross.quantize(_MONEY, ROUND_HALF_UP),
        "unrealized_pnl_gross": portfolio.unrealized_pnl_gross(final_marks).quantize(
            _MONEY, ROUND_HALF_UP
        ),
        "ending_cash": portfolio.cash.quantize(_MONEY, ROUND_HALF_UP),
        "rejected_orders": rejected_orders,
        "unexecuted_orders": unexecuted_orders,
        "decision_cycles": decision_cycles,
        "exit_costs_included": False,
    }
