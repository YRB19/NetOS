"""PromotionCandidate (Stage 3 §2, §14) — an Experiment's output packaged
for human review.

`decision` is `None` until an operator decides — see the `PromotionDecision`
docstring in `enums.py` for why "not yet reviewed" is never confused with
"reviewed and rejected." This module defines the *data shape* only; the
structural enforcement that only an authenticated operator action may set
`decision` (Stage 3 §14: "no automated job... can set this field") belongs
to the governance/promotion machinery, not to the domain object itself —
a domain object cannot, by definition, enforce who is allowed to construct
it. That said, once `decision` is set, this object is immutable, so a
decision can never be silently changed after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.models._validators import require_aware_utc, require_non_empty_str, require_uuid_like
from domain.models.enums import PromotionDecision
from shared.versioning.identifiers import new_id


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    experiment_id: str  # FK -> Experiment.experiment_id
    evaluation_run_id: str  # FK -> EvaluationRun.run_id
    candidate_id: str = field(default_factory=new_id)
    reviewer: str | None = None
    decision: PromotionDecision | None = None
    decision_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        require_uuid_like(self.experiment_id, "experiment_id")
        require_uuid_like(self.evaluation_run_id, "evaluation_run_id")
        require_uuid_like(self.candidate_id, "candidate_id")

        decided = self.decision is not None
        has_reviewer = self.reviewer is not None
        has_timestamp = self.decision_timestamp is not None

        if decided != has_reviewer or decided != has_timestamp:
            raise ValueError(
                "decision, reviewer, and decision_timestamp must all be set together "
                "or all be None — a decision without a reviewer or timestamp (or vice "
                "versa) is not a valid, attributable review record."
            )
        if has_reviewer:
            require_non_empty_str(self.reviewer, "reviewer")
        if self.decision is not None and not isinstance(self.decision, PromotionDecision):
            raise ValueError(
                f"decision must be a PromotionDecision or None, got: {self.decision!r}"
            )
        if self.decision_timestamp is not None:
            object.__setattr__(
                self,
                "decision_timestamp",
                require_aware_utc(self.decision_timestamp, "decision_timestamp"),
            )

    def is_decided(self) -> bool:
        return self.decision is not None
