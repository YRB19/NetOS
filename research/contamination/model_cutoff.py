"""Model knowledge-cutoff contamination check (Slice 11, ER-3).

An evaluation whose test window starts on/before the model's declared knowledge cutoff may have
been memorised by the model; it can never be classified CONFIRMATORY. An UNKNOWN cutoff is carried
as a far-future sentinel by `ModelVersion`, so it always overlaps => fails closed.
"""

from __future__ import annotations

from enum import Enum

from domain.models.research_artifacts import ContaminationCheckResult, SplitSpec
from domain.models.versions import ModelVersion
from research.harness.failures import FailureCategory, ResearchRunFailure


class EvaluationClass(str, Enum):  # noqa: UP042
    CONFIRMATORY_ELIGIBLE = "CONFIRMATORY_ELIGIBLE"
    EXPLORATORY_ONLY = "EXPLORATORY_ONLY"


def evaluate_model_cutoff(
    model_version: ModelVersion, split: SplitSpec
) -> tuple[ContaminationCheckResult, EvaluationClass]:
    """Pure classification. Evaluation of any window that overlaps the cutoff is EXPLORATORY_ONLY."""
    cutoff = model_version.knowledge_cutoff
    overlap = split.test_start <= cutoff
    if overlap:
        return (
            ContaminationCheckResult(
                passed=False,
                overlap_detected=True,
                detail=(
                    f"test window starts {split.test_start.isoformat()} on/before model knowledge cutoff "
                    f"{cutoff.isoformat()}; result is EXPLORATORY_ONLY (never confirmatory)"
                ),
            ),
            EvaluationClass.EXPLORATORY_ONLY,
        )
    return (
        ContaminationCheckResult(
            passed=True,
            overlap_detected=False,
            detail=f"test window starts after model knowledge cutoff {cutoff.isoformat()}",
        ),
        EvaluationClass.CONFIRMATORY_ELIGIBLE,
    )


def enforce_confirmatory(model_version: ModelVersion, split: SplitSpec) -> ContaminationCheckResult:
    """Fail closed: raise CONTAMINATION when a confirmatory run overlaps the model's knowledge period."""
    result, cls = evaluate_model_cutoff(model_version, split)
    if cls is not EvaluationClass.CONFIRMATORY_ELIGIBLE:
        raise ResearchRunFailure(FailureCategory.CONTAMINATION, result.detail)
    return result
