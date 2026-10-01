"""ResearchRunResult — the in-memory form of one research run (Slice 5, spec §6, §24, §26).

It WRAPS the existing canonical contracts (`Experiment`, `EvaluationRun`,
`DecisionRecord`) rather than competing with them. Everything except `created_at`
is a deterministic function of the experiment configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.models.decision_record import DecisionRecord
from domain.models.research_artifacts import EvaluationRun, Experiment
from research.harness.failures import ResearchFailureRecord, RunStatus


@dataclass(frozen=True)
class ResearchRunResult:
    run_id: str
    experiment_id: str
    status: RunStatus
    strategy_version_id: str
    baseline_strategy_version_ids: tuple[str, ...]
    feature_set_version: str
    cost_schedule_version: str
    data_snapshot_version: str
    universe_schedule: tuple[tuple[str, str], ...]  # (universe version, effective_from iso)
    config: dict
    comparison_fingerprint: str
    harness_version: str
    window_start: str | None
    window_end: str | None
    initial_capital: str
    metrics: dict | None
    contamination_report: dict
    decisions: tuple[dict, ...] = ()
    trades: tuple[dict, ...] = ()
    rejections: tuple[dict, ...] = ()
    equity_curve: tuple[dict, ...] = ()
    final_positions: tuple[dict, ...] = ()
    decision_records: tuple[DecisionRecord, ...] = ()
    failure: ResearchFailureRecord | None = None
    experiment: Experiment | None = None
    evaluation_run: EvaluationRun | None = None
    criteria_assessment: str = "NOT_ASSESSED"
    created_at: datetime | None = field(default=None, compare=False)  # metadata only

    @property
    def succeeded(self) -> bool:
        return self.status is RunStatus.COMPLETED and self.failure is None

    def deterministic_summary(self) -> dict:
        """The part of the result that must be identical across re-runs."""
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "status": self.status,
            "strategy_version_id": self.strategy_version_id,
            "baseline_strategy_version_ids": self.baseline_strategy_version_ids,
            "feature_set_version": self.feature_set_version,
            "cost_schedule_version": self.cost_schedule_version,
            "data_snapshot_version": self.data_snapshot_version,
            "universe_schedule": self.universe_schedule,
            "config": self.config,
            "comparison_fingerprint": self.comparison_fingerprint,
            "harness_version": self.harness_version,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "initial_capital": self.initial_capital,
            "metrics": self.metrics,
            "contamination_report": self.contamination_report,
            "failure": self.failure.to_dict() if self.failure else None,
            "criteria_assessment": self.criteria_assessment,
            "final_positions": self.final_positions,
        }
