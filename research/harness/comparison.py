"""Apples-to-apples strategy-vs-baseline comparison (Slice 5, spec §19, §21).

Both runs must have an identical `comparison_fingerprint`: same data snapshot, universe
schedule, window, initial capital, cost schedule and execution assumptions. All metrics
are NET of costs on both sides. There is deliberately NO statistical test here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.models.market_data import MarketData
from data.features.universe import PermittedUniverse
from research.harness.config import ResearchConfig
from research.harness.failures import RunStatus
from research.harness.result import ResearchRunResult
from research.harness.runner import ResearchHarness

_DIFF_KEYS = (
    "final_equity", "net_pnl", "gross_pnl", "total_transaction_costs", "total_return",
    "number_of_transactions", "turnover",
)  # fmt: skip


class ComparisonError(ValueError):
    pass


@dataclass(frozen=True)
class ComparisonResult:
    strategy_run_id: str
    baseline_run_id: str
    comparison_fingerprint: str
    basis: str
    shared_configuration: dict
    strategy_metrics: dict
    baseline_metrics: dict
    differences: dict  # strategy minus baseline

    def to_dict(self) -> dict:
        return {
            "strategy_run_id": self.strategy_run_id,
            "baseline_run_id": self.baseline_run_id,
            "comparison_fingerprint": self.comparison_fingerprint,
            "basis": self.basis,
            "shared_configuration": self.shared_configuration,
            "strategy_metrics": self.strategy_metrics,
            "baseline_metrics": self.baseline_metrics,
            "differences_strategy_minus_baseline": self.differences,
            "statistical_significance": "NOT_ASSESSED",
        }


def compare_runs(strategy: ResearchRunResult, baseline: ResearchRunResult) -> ComparisonResult:
    for label, r in (("strategy", strategy), ("baseline", baseline)):
        if r.status is not RunStatus.COMPLETED or r.metrics is None:
            raise ComparisonError(f"{label} run {r.run_id} did not complete; cannot compare")
    if strategy.comparison_fingerprint != baseline.comparison_fingerprint:
        raise ComparisonError(
            "runs are not apples-to-apples: data, universe, window, capital, cost schedule or "
            "execution configuration differ"
        )
    if strategy.metrics["basis"] != baseline.metrics["basis"]:
        raise ComparisonError("metric bases differ (net vs gross); refusing to compare")
    diffs = {}
    for k in _DIFF_KEYS:
        a, b = strategy.metrics[k], baseline.metrics[k]
        diffs[k] = a - b
    shared = {
        k: strategy.config[k]
        for k in ("initial_capital", "cost_schedule_version", "split", "evaluation_period",
                  "execution_assumption", "allocation_cash_buffer", "feature_set_id")
    }  # fmt: skip
    shared["data_snapshot_version"] = strategy.data_snapshot_version
    shared["universe_schedule"] = [list(u) for u in strategy.universe_schedule]
    return ComparisonResult(
        strategy_run_id=strategy.run_id,
        baseline_run_id=baseline.run_id,
        comparison_fingerprint=strategy.comparison_fingerprint,
        basis=strategy.metrics["basis"],
        shared_configuration=shared,
        strategy_metrics=strategy.metrics,
        baseline_metrics=baseline.metrics,
        differences=diffs,
    )


def run_with_baseline(
    harness: ResearchHarness,
    config: ResearchConfig,
    strategy: object,
    baseline: object,
    market_data: list[MarketData],
    universe_schedule: list[PermittedUniverse],
    created_at: datetime | None = None,
) -> tuple[ResearchRunResult, ResearchRunResult, ComparisonResult | None]:
    """Run candidate and baseline under the identical configuration; compare if both complete."""
    baseline_id = str(getattr(baseline, "strategy_version_id", "UNKNOWN_STRATEGY"))
    s = harness.run(config, strategy, market_data, universe_schedule, (baseline_id,), created_at)
    b = harness.run(config, baseline, market_data, universe_schedule, (baseline_id,), created_at)
    try:
        cmp = compare_runs(s, b)
    except ComparisonError:
        cmp = None
    return s, b, cmp
