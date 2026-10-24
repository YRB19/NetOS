"""Failure taxonomy for the research harness (Slice 5, spec §24).

A failed research run is a first-class artifact, never a lost exception. Every
failure the harness can anticipate is raised as `ResearchRunFailure` carrying a
`FailureCategory` and a JSON-safe `context`; the runner converts it into a
persisted `ResearchFailureRecord` and marks the run FAILED (never COMPLETED).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FailureCategory(str, Enum):  # noqa: UP042 - matches repository enum convention
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_DATA = "INVALID_DATA"
    MISSING_DATA = "MISSING_DATA"
    DUPLICATE_DATA = "DUPLICATE_DATA"
    CONTAMINATION = "CONTAMINATION"
    STRATEGY_ERROR = "STRATEGY_ERROR"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    MISSING_EXECUTION_PRICE = "MISSING_EXECUTION_PRICE"
    ACCOUNTING_ERROR = "ACCOUNTING_ERROR"
    # Slice 6 (additive): execution-pipeline failure categories
    BROKER_REJECTED = "BROKER_REJECTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    SIZING_REFUSED = "SIZING_REFUSED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
    # Slice 7 final closure (additive): portfolio checkpoint could not be written / read / validated
    PORTFOLIO_CHECKPOINT_ERROR = "PORTFOLIO_CHECKPOINT_ERROR"


class RunStatus(str, Enum):  # noqa: UP042
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ResearchRunFailure(Exception):
    """Raised inside the harness to abort a run with a categorised, recorded reason."""

    def __init__(self, category: FailureCategory, message: str, **context: object) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.context = dict(context)


@dataclass(frozen=True)
class ResearchFailureRecord:
    """The persisted, reconstructable description of why a run failed."""

    category: FailureCategory
    message: str
    failed_at_decision: str | None = None  # ISO-8601 UTC decision timestamp, if applicable
    context: dict = field(default_factory=dict)
    contamination_detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "message": self.message,
            "failed_at_decision": self.failed_at_decision,
            "context": self.context,
            "contamination_detail": self.contamination_detail,
        }
