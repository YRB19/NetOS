"""Experiment / EvaluationRun (Stage 3 §2, §11).

Both immutable once completed and NEVER deleted — including failed
experiments — because ER-4's PBO/CSCV-style multiple-testing correction
requires the full attempted-variant set, not just the reported winner
(Stage 3 §11: "the harness's storage schema makes 'hide the failures'
structurally difficult"). These are domain data shapes only; the harness
logic that produces and consumes them (`research/harness/`) is later work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.models._validators import require_aware_utc, require_non_empty_str, require_uuid_like
from shared.time.clock import utc_now
from shared.versioning.identifiers import new_id


@dataclass(frozen=True, slots=True)
class SplitSpec:
    """A declared chronological train/validation/test split (ER-2).

    The harness "refuses to execute" a run without one of these declared
    (Stage 3 §11) — this type is what makes that a checkable precondition
    rather than a convention.
    """

    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        fields = [
            self.train_start,
            self.train_end,
            self.validation_start,
            self.validation_end,
            self.test_start,
            self.test_end,
        ]
        for f in fields:
            require_aware_utc(f, "split boundary")
        ordered = fields == sorted(fields)
        if not ordered:
            raise ValueError(
                "SplitSpec boundaries must be strictly chronological: "
                "train_start <= train_end <= validation_start <= validation_end "
                "<= test_start <= test_end (ER-2: no leakage across a declared split)."
            )


@dataclass(frozen=True, slots=True)
class Experiment:
    hypothesis: str
    candidate_strategy_version: str  # FK -> StrategyVersion.version_id
    baseline_strategy_versions: tuple[str, ...]  # FK(s) -> StrategyVersion.version_id
    evaluation_window: SplitSpec
    pre_registered_criteria: str  # ER-8: declared BEFORE results are seen
    experiment_id: str = field(default_factory=new_id)
    result_summary: str | None = None
    promoted: bool = False
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_non_empty_str(self.hypothesis, "hypothesis")
        require_uuid_like(self.candidate_strategy_version, "candidate_strategy_version")
        if not self.baseline_strategy_versions:
            raise ValueError(
                "baseline_strategy_versions must not be empty — ER-1 requires every "
                "candidate to be compared against at least one declared baseline."
            )
        if not isinstance(self.evaluation_window, SplitSpec):
            raise ValueError("evaluation_window must be a SplitSpec")
        require_non_empty_str(self.pre_registered_criteria, "pre_registered_criteria")
        require_uuid_like(self.experiment_id, "experiment_id")
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class ContaminationCheckResult:
    passed: bool
    detail: str
    overlap_detected: bool = False
    operator_override: bool = False
    override_justification: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_str(self.detail, "detail")
        if self.operator_override and not self.override_justification:
            raise ValueError(
                "operator_override=True requires a logged override_justification "
                "(ER-3: an override must be explicit and recorded, never silent)."
            )


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    experiment_id: str  # FK -> Experiment.experiment_id
    data_version: str
    split: SplitSpec
    contamination_check: ContaminationCheckResult
    pbo_cscv_correction_applied: bool
    regime_segmented_results: dict  # e.g. {"rising": {...}, "falling": {...}, "range_bound": {...}}
    passed_pre_registered_criteria: bool
    run_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        require_uuid_like(self.experiment_id, "experiment_id")
        require_non_empty_str(self.data_version, "data_version")
        if not isinstance(self.split, SplitSpec):
            raise ValueError("split must be a SplitSpec")
        if not isinstance(self.contamination_check, ContaminationCheckResult):
            raise ValueError("contamination_check must be a ContaminationCheckResult")
        require_uuid_like(self.run_id, "run_id")
        if not isinstance(self.regime_segmented_results, dict):
            raise ValueError("regime_segmented_results must be a dict")
        from types import MappingProxyType

        object.__setattr__(
            self, "regime_segmented_results", MappingProxyType(dict(self.regime_segmented_results))
        )
