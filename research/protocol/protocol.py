"""Versioned, hash-frozen experiment protocol (Slice 9, ADR-15).

A protocol freezes WHAT is being tested before evaluation starts. Free-text criteria are
rationale only; only `AcceptanceCriterion` objects are machine-assessed, and only against
metrics the harness can actually produce. No numeric threshold is ever defaulted here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from domain.models.research_artifacts import SplitSpec
from research.harness.jsonio import jsonable
from shared.versioning.content_hash import hash_json_stable

PROTOCOL_SCHEMA_VERSION = "experiment-protocol-v1"


class ExperimentMode(str, Enum):  # noqa: UP042
    EXPLORATORY = "EXPLORATORY"
    CONFIRMATORY = "CONFIRMATORY"


class HoldoutReusePolicy(str, Enum):  # noqa: UP042
    REJECT = "REJECT"  # a second exposure is refused
    DOWNGRADE_TO_NON_CONFIRMATORY = "DOWNGRADE_TO_NON_CONFIRMATORY"


class Comparator(str, Enum):  # noqa: UP042
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"


@dataclass(frozen=True)
class AcceptanceCriterion:
    """A machine-assessable criterion. `threshold` is supplied by the researcher (a decimal
    string); the system never invents one. `adverse=True` marks a criterion whose
    satisfaction means an ADVERSE result (e.g. drawdown above a stated limit)."""

    metric: str
    comparator: Comparator
    threshold: str
    rationale: str
    adverse: bool = False


@dataclass(frozen=True)
class ExperimentProtocol:
    protocol_id: str  # stable family name
    version: int  # 1, 2, ... a change creates a new version
    mode: ExperimentMode
    hypothesis: str
    research_question: str
    universe_policy: str
    universe_versions: tuple[str, ...]
    dataset_id: str
    dataset_version: str
    data_start: datetime
    data_end: datetime
    sampling_frequency: str
    availability_requirement: str  # e.g. "SOURCE_AVAILABILITY_REQUIRED" | "NOT_REQUIRED_SYNTHETIC"
    split: SplitSpec
    strategy_version_ids: tuple[str, ...]
    benchmark_version_ids: tuple[str, ...]
    cost_schedule_version: str
    entry_exit_cost_assumption: str
    execution_assumptions: Mapping[str, str]
    unverified_elements: tuple[str, ...]
    primary_metrics: tuple[str, ...]
    secondary_metrics: tuple[str, ...]
    metric_definitions_version: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    negative_result_definition: str
    holdout_id: str
    holdout_reuse_policy: HoldoutReusePolicy
    strategy_configured_through: datetime | None = None
    information_horizon_days: int | None = None
    embargo_days: int | None = None
    parameter_space: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    trial_budget: int | None = None
    regime_definition_id: str | None = None
    links: Mapping[str, str] = field(default_factory=dict)  # journal/dataset/code hashes
    supersedes_protocol_hash: str | None = None

    def validate(self) -> list[str]:
        errs: list[str] = []
        for n in ("protocol_id", "hypothesis", "research_question", "dataset_id",
                  "dataset_version", "cost_schedule_version", "holdout_id",
                  "metric_definitions_version", "negative_result_definition"):  # fmt: skip
            v = getattr(self, n)
            if not isinstance(v, str) or not v.strip():
                errs.append(f"{n} must be a non-empty string")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            errs.append("version must be an integer >= 1")
        if self.version > 1 and not self.supersedes_protocol_hash:
            errs.append("version > 1 must reference supersedes_protocol_hash")
        if self.version == 1 and self.supersedes_protocol_hash:
            errs.append("version 1 cannot supersede another protocol")
        if not self.strategy_version_ids:
            errs.append("strategy_version_ids must not be empty")
        if not self.benchmark_version_ids:
            errs.append("benchmark_version_ids must not be empty (ER-1)")
        if not self.primary_metrics:
            errs.append("primary_metrics must not be empty")
        if self.data_start > self.data_end:
            errs.append("data_start must not be after data_end")
        if self.mode is ExperimentMode.CONFIRMATORY:
            if not self.acceptance_criteria:
                errs.append("a confirmatory protocol needs structured acceptance_criteria")
            if self.information_horizon_days is None:
                errs.append("a confirmatory protocol must declare information_horizon_days "
                            "(0 is allowed with justification in the unverified/links notes)")
            if self.strategy_configured_through is None:
                errs.append("a confirmatory protocol must declare strategy_configured_through")
        for c in self.acceptance_criteria:
            if c.metric not in set(self.primary_metrics) | set(self.secondary_metrics):
                errs.append(f"criterion metric {c.metric!r} is not a declared metric")
            try:
                float(c.threshold)
            except (TypeError, ValueError):
                errs.append(f"criterion threshold for {c.metric!r} is not numeric: {c.threshold!r}")
        for h, n in ((self.information_horizon_days, "information_horizon_days"),
                     (self.embargo_days, "embargo_days")):  # fmt: skip
            if h is not None and (isinstance(h, bool) or not isinstance(h, int) or h < 0):
                errs.append(f"{n} must be a non-negative int or None")
        return errs

    def payload(self) -> dict:
        p = jsonable(self)
        assert isinstance(p, dict)
        p["__schema__"] = PROTOCOL_SCHEMA_VERSION
        return p

    def protocol_hash(self) -> str:
        return hash_json_stable(self.payload())
