"""Extended research metrics (Slice 9, ADR-19). Additive: old metrics are untouched.

Every metric is {value, status, unit, denominator, definition, reason}. Decimal throughout;
a value that cannot be computed is None with a reason, never 0. Statistical figures
(volatility) use Decimal with 28-digit context, quantised to 1e-10.
Returns are PER DECISION CYCLE (irregular calendar spacing); annualisation only when an
explicit periods-per-year and justification are supplied.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from domain.models.market_data import MarketData
from research.harness.result import ResearchRunResult
from research.validity.assumptions import ExecutionAssumptions
from shared.costs import CostInputs, CostModel, TradeType, TransactionSide

METRIC_DEFINITIONS_VERSION = "metrics-v2-slice9"
_Q = Decimal("1e-10")
_M = Decimal("0.01")


def _m(value, unit: str, denominator: str, definition: str, status: str = "OK", reason: str | None = None) -> dict:
    return {"value": None if value is None else str(value), "status": status, "unit": unit,
            "denominator": denominator, "definition": definition, "reason": reason}  # fmt: skip


def _na(unit, definition, reason, status="UNAVAILABLE"):
    return _m(None, unit, "n/a", definition, status, reason)


def final_marks_from_market_data(result: ResearchRunResult, market_data: list[MarketData]) -> dict[str, Decimal] | None:
    """Last close on/before the final equity timestamp for each held instrument; None if any
    held instrument has no such bar (no fabricated price)."""
    if not result.equity_curve:
        return None
    last_ts = result.equity_curve[-1]["timestamp"]
    marks: dict[str, Decimal] = {}
    for pos in result.final_positions:
        cands = [m for m in market_data if m.instrument_id == pos["instrument_id"] and m.timestamp <= last_ts]
        if not cands:
            return None
        marks[pos["instrument_id"]] = Decimal(str(max(cands, key=lambda m: m.timestamp).close))
    return marks


def compute_extended_metrics(
    result: ResearchRunResult, *, cost_model: CostModel,
    final_marks: Mapping[str, Decimal] | None, assumptions: ExecutionAssumptions | None = None,
    baseline: ResearchRunResult | None = None, unique_trial_count: int | None = None,
    annualisation_periods_per_year: int | None = None, annualisation_justification: str | None = None,
) -> dict:  # fmt: skip
    assumptions = assumptions or ExecutionAssumptions()
    if result.metrics is None or not result.equity_curve:
        return {"status": "UNAVAILABLE", "reason": "run did not complete or has no equity curve",
                "definitions_version": METRIC_DEFINITIONS_VERSION}  # fmt: skip
    base = result.metrics
    initial = Decimal(base["initial_capital"])
    eq = [Decimal(r["equity"]) for r in result.equity_curve]
    out: dict = {"definitions_version": METRIC_DEFINITIONS_VERSION, "status": "OK"}
    out["final_equity"] = _m(eq[-1].quantize(_M), "INR", "1 run", "mark-to-market equity at last decision cycle")
    out["net_return"] = _m(base["total_return"], "fraction", "initial_capital", "(final_equity - initial)/initial; costs booked, unliquidated")  # fmt: skip
    out["gross_pnl"] = _m(base["gross_pnl"], "INR", "1 run", "net_pnl + booked transaction costs")
    out["net_pnl"] = _m(base["net_pnl"], "INR", "1 run", "final_equity - initial_capital")
    out["decision_cycles"] = _m(base["decision_cycles"], "count", "1 run", "decision cycles in window")
    out["transactions"] = _m(base["number_of_transactions"], "count", "1 run", "executed fills")
    out["fills"] = _m(len(result.trades), "count", "1 run", "rows in trades.jsonl")
    out["rejected_orders"] = _m(base["rejected_orders"], "count", "1 run", "rejected simulated orders")
    out["unexecuted_orders"] = _m(base["unexecuted_orders"], "count", "1 run", "pending at window end")
    out["unique_trial_count"] = (
        _m(unique_trial_count, "count", "trial ledger", "trials in the ledger for this protocol")
        if unique_trial_count is not None else _na("count", "trials in the ledger", "no trial ledger supplied"))  # fmt: skip
    # costs: actual booked, split by leg from the persisted trades
    buy_c = sell_c = Decimal(0)
    for t in result.trades:
        c = Decimal(str(t["cost_estimate"].total_cost))
        if t["side"] == "BUY":
            buy_c += c
        else:
            sell_c += c
    out["actual_entry_costs"] = _m(buy_c, "INR", "BUY fills", "sum of CostEstimate.total_cost on BUY fills (actually booked)")
    out["actual_exit_costs"] = _m(sell_c, "INR", "SELL fills", "sum of CostEstimate.total_cost on SELL fills (actually booked)")
    out["total_actual_costs"] = _m(buy_c + sell_c, "INR", "all fills", "booked transaction costs")
    out["reconciliation_actual_costs_vs_portfolio"] = _m(
        (buy_c + sell_c).quantize(_M) == Decimal(base["total_transaction_costs"]), "bool", "1 run",
        "trade-level costs equal portfolio cumulative costs")  # fmt: skip
    out["cost_drag"] = _m((buy_c + sell_c) / initial, "fraction", "initial_capital", "total actual costs / initial capital")
    out["turnover_to_capital"] = _m(base["turnover_to_initial_capital"], "fraction", "initial_capital", "cumulative traded value / initial capital")  # fmt: skip
    out["realized_pnl_gross"] = _m(base["realized_pnl_gross"], "INR", "1 run", "realized P&L before costs")
    out["unrealized_pnl_gross"] = _m(base["unrealized_pnl_gross"], "INR", "1 run", "unrealized P&L before costs")
    # drawdown
    peak, mdd, mdd_abs = eq[0], Decimal(0), Decimal(0)
    for e in eq:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
        mdd_abs = max(mdd_abs, peak - e)
    out["max_drawdown"] = _m(mdd.quantize(_Q, ROUND_HALF_UP), "fraction", f"{len(eq)} equity points", "max (running_peak - equity)/running_peak over the persisted equity curve")  # fmt: skip
    out["max_drawdown_inr"] = _m(mdd_abs.quantize(_M), "INR", f"{len(eq)} equity points", "max (running_peak - equity)")
    # exposure
    expo = [Decimal(r["market_value"]) / Decimal(r["equity"]) for r in result.equity_curve if Decimal(r["equity"]) != 0]
    out["average_exposure"] = _m((sum(expo) / len(expo)).quantize(_Q), "fraction", f"{len(expo)} cycles", "mean market_value/equity") if expo else _na("fraction", "mean market_value/equity", "no equity points")  # fmt: skip
    out["max_exposure"] = _m(max(expo).quantize(_Q), "fraction", f"{len(expo)} cycles", "max market_value/equity") if expo else _na("fraction", "max market_value/equity", "no equity points")  # fmt: skip
    # volatility
    rets = [eq[i + 1] / eq[i] - 1 for i in range(len(eq) - 1) if eq[i] != 0]
    vdef = "sample stdev (n-1) of per-decision-cycle simple equity returns"
    if len(rets) >= 2:
        m = sum(rets) / len(rets)
        sd = (sum((r - m) ** 2 for r in rets) / (len(rets) - 1)).sqrt()
        out["periodic_volatility"] = _m(sd.quantize(_Q), "fraction per cycle", f"{len(rets)} returns", vdef)
        if annualisation_periods_per_year and annualisation_justification:
            out["annualised_volatility"] = _m((sd * Decimal(annualisation_periods_per_year).sqrt()).quantize(_Q), "fraction per year", f"{len(rets)} returns",
                                              f"periodic * sqrt({annualisation_periods_per_year}); justification: {annualisation_justification}")  # fmt: skip
        else:
            out["annualised_volatility"] = _na("fraction per year", "periodic * sqrt(periods_per_year)", "no explicit, justified annualisation convention supplied", "UNSUPPORTED")  # fmt: skip
    else:
        out["periodic_volatility"] = _m(None, "fraction per cycle", f"{len(rets)} returns", vdef, "INSUFFICIENT_SAMPLE", "need >= 2 returns")  # fmt: skip
        out["annualised_volatility"] = _na("fraction per year", "periodic * sqrt(periods_per_year)", "insufficient sample", "INSUFFICIENT_SAMPLE")  # fmt: skip
    # terminal liquidation: ESTIMATED, kept apart from booked costs
    tl: dict
    if not result.final_positions:
        tl = {"status": "NOT_APPLICABLE", "estimated_cost": "0.00", "reason": "no open positions at window end"}
    elif final_marks is None or any(p["instrument_id"] not in final_marks for p in result.final_positions):
        tl = {"status": "UNAVAILABLE", "estimated_cost": None, "reason": "no supported mark price for every open position"}
    else:
        total, proceeds_adj = Decimal(0), Decimal(0)
        slip = assumptions.terminal_slippage_bps
        for p in result.final_positions:
            px = final_marks[p["instrument_id"]]
            if slip is not None:
                px = px * (1 - slip / Decimal(10000))
            est = cost_model.estimate(CostInputs(TransactionSide.SELL, TradeType.DELIVERY, p["quantity"], px, base_schedule(result)))  # noqa: E501
            total += est.total_cost
            proceeds_adj += Decimal(p["quantity"]) * (final_marks[p["instrument_id"]] - px)
        tl = {"status": "ESTIMATED_ASSUMPTION_BASED", "estimated_cost": str(total),
              "assumed_slippage_cost": str(proceeds_adj.quantize(_M)),
              "result_after_terminal_liquidation": str((eq[-1] - total - proceeds_adj).quantize(_M)),
              "return_after_terminal_liquidation": str(((eq[-1] - total - proceeds_adj) / initial - 1).quantize(_Q)),
              "note": "hypothetical liquidation at last mark; NOT an executed cost"}  # fmt: skip
    out["terminal_liquidation"] = tl
    # baseline-relative
    if baseline is None:
        out["baseline_relative_return"] = _na("fraction", "net_return(strategy) - net_return(baseline)", "no baseline supplied")
    elif baseline.metrics is None or baseline.comparison_fingerprint != result.comparison_fingerprint:
        out["baseline_relative_return"] = _na("fraction", "net_return(strategy) - net_return(baseline)",
                                              "NON_COMPARABLE: data, window, universe, cost schedule or execution differ, or baseline incomplete", "NON_COMPARABLE")  # fmt: skip
    else:
        out["baseline_relative_return"] = _m(Decimal(base["total_return"]) - Decimal(baseline.metrics["total_return"]), "fraction", "matched window/fingerprint", "net_return(strategy) - net_return(baseline), same fingerprint")  # fmt: skip
    out["execution_assumptions"] = assumptions.disclosures()
    return out


def base_schedule(result: ResearchRunResult) -> str:
    return result.cost_schedule_version
