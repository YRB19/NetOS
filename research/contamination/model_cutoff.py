"""Model knowledge-cutoff contamination check (Slice 11, ER-3).

An evaluation whose test window starts on/before the model's declared knowledge cutoff may have
been memorised by the model; it can never be classified CONFIRMATORY. An UNKNOWN cutoff is carried
as a far-future sentinel by `ModelVersion`, so it always overlaps => fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from domain.models.research_artifacts import ContaminationCheckResult, SplitSpec
from domain.models.versions import ModelVersion
from research.harness.failures import FailureCategory, ResearchRunFailure


class EvaluationClass(str, Enum):  # noqa: UP042
    CONFIRMATORY_ELIGIBLE = "CONFIRMATORY_ELIGIBLE"
    EXPLORATORY_ONLY = "EXPLORATORY_ONLY"


def evaluate_model_cutoff(model_version: ModelVersion, split: SplitSpec) -> tuple[ContaminationCheckResult, EvaluationClass]:
    """Pure classification. Evaluation of any window that overlaps the cutoff is EXPLORATORY_ONLY."""
    cutoff = model_version.knowledge_cutoff
    overlap = split.test_start <= cutoff
    if overlap:
        return (
            ContaminationCheckResult(
                passed=False, overlap_detected=True,
                detail=(f"test window starts {split.test_start.isoformat()} on/before model knowledge cutoff "
                        f"{cutoff.isoformat()}; result is EXPLORATORY_ONLY (never confirmatory)"),
            ),
            EvaluationClass.EXPLORATORY_ONLY,
        )
    return (
        ContaminationCheckResult(
            passed=True, overlap_detected=False,
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


# ---------------------------------------------------------------------------
# Integration with the enforced evaluation service (Slice 11 closure)
# ---------------------------------------------------------------------------
_DOCUMENTED = "PROVIDER_DOCUMENTED"


@dataclass(frozen=True)
class AiModelAssessment:
    evaluation_class: EvaluationClass
    reasons: tuple[str, ...]
    provenance: dict  # exactly what is persisted in the evaluation report


def assess_ai_model(model_version: ModelVersion | None, provenance: dict | None, split: SplitSpec) -> AiModelAssessment:
    """Confirmatory eligibility of an AI-enabled evaluation. Fails closed on EVERY uncertainty.

    Nothing is inferred or invented: missing/unlinked metadata, an unknown/undeclared cutoff, a
    cutoff without a source note, inconsistent provenance, or any overlap with the model's declared
    knowledge period each make the evaluation EXPLORATORY_ONLY.
    """
    reasons: list[str] = []
    prov = dict(provenance) if provenance else {}
    persisted = {
        "model_version_id": prov.get("model_version_id") or (model_version.version_id if model_version else None),
        "backbone_identifier": prov.get("backbone_identifier") or (model_version.backbone_identifier if model_version else None),
        "cutoff_basis": prov.get("cutoff_basis"),
        "cutoff_date": prov.get("cutoff_date"),
        "cutoff_source_note": prov.get("cutoff_source_note"),
        "model_version_cutoff": model_version.knowledge_cutoff.isoformat() if model_version else None,
        "test_start": split.test_start.isoformat(),
    }
    if model_version is None:
        reasons.append("MODEL_VERSION_UNLINKED: AI-enabled evaluation has no ModelVersion")
    if not provenance:
        reasons.append("MODEL_CUTOFF_PROVENANCE_MISSING: no cutoff provenance supplied")
    else:
        if model_version is not None and prov.get("model_version_id") != model_version.version_id:
            reasons.append("MODEL_PROVENANCE_MISMATCH: provenance is not for this ModelVersion")
        basis, date, note = prov.get("cutoff_basis"), prov.get("cutoff_date"), (prov.get("cutoff_source_note") or "").strip()
        if basis != _DOCUMENTED or not date or not note:
            reasons.append(f"MODEL_CUTOFF_UNKNOWN: cutoff basis {basis!r} with no documented date and source note")
        elif model_version is not None:
            try:
                declared = datetime.fromisoformat(date)
            except ValueError:
                declared = None
            if declared != model_version.knowledge_cutoff:
                reasons.append("MODEL_CUTOFF_INCONSISTENT: provenance cutoff differs from ModelVersion.knowledge_cutoff")
    if model_version is not None and split.test_start <= model_version.knowledge_cutoff:
        reasons.append(
            f"MODEL_KNOWLEDGE_PERIOD_OVERLAP: test window starts {split.test_start.isoformat()} on/before "
            f"model knowledge cutoff {model_version.knowledge_cutoff.isoformat()}"
        )
    cls = EvaluationClass.EXPLORATORY_ONLY if reasons else EvaluationClass.CONFIRMATORY_ELIGIBLE
    persisted["evaluation_class"] = cls.value
    persisted["reasons"] = list(reasons)
    return AiModelAssessment(cls, tuple(reasons), persisted)
