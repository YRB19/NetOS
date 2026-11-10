"""Frozen outcome classifier (Slice 12). Outcome A-D derived by fixed rules, in this order.

The rules reference only fields of the frozen `AIEvaluationSpec` and measured inputs; nothing is
judged after viewing results. Evidence-class and integrity caps are applied BEFORE performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from research.ai_eval.spec import CONFIRMATORY_GRADE, EVIDENCE_CLASSES, AIEvaluationSpec

RULES_VERSION = "ai-eval-decision-rules-v1"
OUTCOMES = {
    "A": "Evidence of incremental value (supports further PAPER evaluation only; not live permission)",
    "B": "Inconclusive (AI component remains experimental)",
    "C": "No demonstrated incremental value (retain the deterministic baseline)",
    "D": "Evidence of harm (disable or redesign the experimental signal)",
}


@dataclass(frozen=True)
class DecisionInputs:
    evidence_class: str  # what was actually measured (never higher than the spec's declared class)
    effective_confirmatory: bool  # enforced evaluation service verdict for the AI arm
    integrity_breaches: int  # applied-but-ineligible signals + failed run-level provenance checks
    n_valid_signals: int
    signal_coverage: float | None
    n_cycles: int
    arm_paths_identical: bool  # AI-enabled equity curve identical to Tier-2
    incremental_trades: int
    delta_net_return: float | None
    ci_lower: float | None
    ci_upper: float | None
    ci_status: str
    drawdown_regression: float | None  # AI - Tier-2 max drawdown (positive = worse)
    cost_increase_fraction: float | None  # (AI cost - T2 cost) / T2 cost


@dataclass(frozen=True)
class OutcomeDecision:
    outcome: str
    label: str
    rule_trace: tuple[str, ...]
    rules_version: str = RULES_VERSION

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "label": self.label, "rule_trace": list(self.rule_trace),
                "rules_version": self.rules_version}  # fmt: skip


def classify_outcome(spec: AIEvaluationSpec, x: DecisionInputs) -> OutcomeDecision:
    t: list[str] = []

    def out(o: str, why: str) -> OutcomeDecision:
        t.append(why)
        return OutcomeDecision(o, OUTCOMES[o], tuple(t))

    t.append(f"frozen spec {spec.spec_id} v{spec.version} hash {spec.spec_hash()[:16]}")
    if x.integrity_breaches > 0:
        return out("D", f"R1 integrity: {x.integrity_breaches} ineligible/leaking signal(s) influenced decisions")
    t.append("R1 integrity: no applied-but-ineligible signals")
    grade = EVIDENCE_CLASSES.index(x.evidence_class) if x.evidence_class in EVIDENCE_CLASSES else -1
    if grade < EVIDENCE_CLASSES.index(CONFIRMATORY_GRADE) or not x.effective_confirmatory:
        return out("B", f"R2 evidence cap: class {x.evidence_class!r}, effective_confirmatory={x.effective_confirmatory}; "
                        "confirmatory-grade evidence (real data, live-captured provider signals, cutoff-clean) is required "
                        "to leave Outcome B")  # fmt: skip
    t.append("R2 evidence class is confirmatory-grade")
    if x.n_valid_signals < spec.min_valid_signals or x.n_cycles < spec.min_cycles or (
        x.signal_coverage is None or Decimal(str(x.signal_coverage)) < Decimal(spec.min_signal_coverage)
    ):
        return out("B", f"R3 power: valid_signals={x.n_valid_signals} (min {spec.min_valid_signals}), "
                        f"cycles={x.n_cycles} (min {spec.min_cycles}), coverage={x.signal_coverage} (min {spec.min_signal_coverage})")  # fmt: skip
    t.append("R3 power/coverage thresholds met")
    if x.arm_paths_identical and x.incremental_trades == 0:
        return out("C", "R4 no mechanism: AI arm path identical to Tier-2 with zero incremental trades; no value can be demonstrated")
    t.append("R4 AI arm differs from Tier-2")
    if x.ci_status != "OK" or x.delta_net_return is None or x.ci_lower is None or x.ci_upper is None:
        return out("B", f"R5 statistics unavailable: ci_status={x.ci_status}")
    harm = (
        x.ci_upper < -float(spec.min_economic_effect)
        or (x.drawdown_regression is not None and x.drawdown_regression > float(spec.max_drawdown_regression))
        or (x.cost_increase_fraction is not None and x.cost_increase_fraction > float(spec.max_cost_increase_fraction))
    )
    if harm:
        return out("D", "R6 harm: CI upper below -min_effect, or drawdown regression / cost increase beyond frozen limits")
    t.append("R6 no harm criterion met")
    if x.ci_lower > float(spec.min_economic_effect):
        return out("A", f"R7 benefit: adjusted CI lower {x.ci_lower:.6g} > min_economic_effect {spec.min_economic_effect}, no regression")
    if x.ci_upper < float(spec.min_economic_effect):
        return out("C", f"R8 no value: adjusted CI upper {x.ci_upper:.6g} < min_economic_effect {spec.min_economic_effect}")
    return out("B", "R9 interval straddles the minimum economic effect: inconclusive")
