"""RiskDecision (Stage 3 §2, §7) — Plane 3's verdict on a CandidateTrade.

Every check evaluated (not only the failing ones) is recorded, per Stage 3
§7's "this is what makes ... 'what risk limits were applied' answerable
without re-deriving anything." Immutable once created.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.models._validators import require_non_empty_str, require_uuid_like
from domain.models.enums import RiskVerdict
from shared.versioning.identifiers import new_id


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    """One named check (e.g. 'RR-1') and its outcome for a single evaluation."""

    check_id: str  # e.g. "RR-1"
    passed: bool
    detail: str  # human-readable explanation, always present (even on pass)
    # Slice 8 (additive, defaulted): the exact observed inputs and configured limits used by this check,
    # captured AT EVALUATION TIME as (name, exact-string-value) pairs. `detail` stays human prose and is not
    # a substitute. An empty tuple means "evidence was not captured" and must never be reconstructed later.
    evidence: tuple[tuple[str, str], ...] = ()
    evaluable: bool = True  # False: the check could not be evaluated (fail closed; passed is then False)

    def __post_init__(self) -> None:
        require_non_empty_str(self.check_id, "check_id")
        require_non_empty_str(self.detail, "detail")
        if not isinstance(self.evidence, tuple) or not all(
            isinstance(p, tuple) and len(p) == 2 and all(isinstance(x, str) for x in p) for p in self.evidence
        ):
            raise ValueError("evidence must be a tuple of (str, str) pairs")
        if not self.evaluable and self.passed:
            raise ValueError("a check that could not be evaluated cannot be recorded as passed")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    candidate_trade_id: str  # FK -> CandidateTrade.candidate_id
    checks_evaluated: tuple[RiskCheckResult, ...]
    final_verdict: RiskVerdict
    risk_rule_version_id: str
    approved_qty: float | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    risk_decision_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        require_uuid_like(self.candidate_trade_id, "candidate_trade_id")
        require_uuid_like(self.risk_rule_version_id, "risk_rule_version_id")
        require_uuid_like(self.risk_decision_id, "risk_decision_id")

        if not isinstance(self.final_verdict, RiskVerdict):
            raise ValueError(f"final_verdict must be a RiskVerdict, got: {self.final_verdict!r}")
        if not self.checks_evaluated:
            raise ValueError(
                "checks_evaluated must not be empty — a RiskDecision with no "
                "recorded checks would be unauditable (Stage 3 §7)."
            )
        if not all(isinstance(c, RiskCheckResult) for c in self.checks_evaluated):
            raise ValueError("checks_evaluated must contain only RiskCheckResult instances")

        any_failed = any(not c.passed for c in self.checks_evaluated)
        if self.final_verdict == RiskVerdict.APPROVE and any_failed:
            raise ValueError(
                "final_verdict cannot be APPROVE while at least one check failed "
                "(fail-closed principle, Stage 2 Principle 7 / Stage 3 §7)."
            )
        if self.final_verdict == RiskVerdict.REJECT and not self.reasons:
            raise ValueError("a REJECT verdict must state at least one reason")
        if self.final_verdict == RiskVerdict.APPROVE and self.approved_qty is None:
            raise ValueError("an APPROVE verdict must include an approved_qty")
        if self.approved_qty is not None and self.approved_qty <= 0:
            raise ValueError(
                f"approved_qty must be positive when present, got: {self.approved_qty!r}"
            )
