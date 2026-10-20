"""ADR-6: Import-graph / dependency-direction enforcement — rule definitions.

This module is the single source of truth for which top-level package may
NOT import which other top-level package (or subpackage). It contains no
scanning logic — see `checker.py` for that — so the *rules themselves* can
be reviewed, diffed, and reasoned about independently of how they're
enforced.

Each rule states: "a module that lives inside `source_package` must never
import anything from `forbidden_prefix` (or any of its subpackages)."

Rationale for each rule is recorded inline and traces back to a specific
Stage 1 requirement or Stage 2/3 design decision — this is deliberate,
per DOC-2's "every requirement/decision states its rationale" discipline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForbiddenImportRule:
    """One directed 'source must never import forbidden' constraint."""

    source_package: str
    forbidden_prefix: str
    rationale: str

    def applies_to_owning_package(self, owning_package: str) -> bool:
        return owning_package == self.source_package or owning_package.startswith(
            self.source_package + "."
        )

    def forbids(self, imported_module: str) -> bool:
        return imported_module == self.forbidden_prefix or imported_module.startswith(
            self.forbidden_prefix + "."
        )


# ---------------------------------------------------------------------------
# Rule set
# ---------------------------------------------------------------------------
#
# NOTE on "governance write interfaces": Stage 3 §1/§14/§16 distinguishes
# operator-writable Plane 0 config from read access to it. At this stage
# (Slice 0/1) the `governance` package contains only config/autonomy/
# killswitch state representations with no read-only-vs-write-only split
# yet implemented (that split is Governance-plane build work, not yet
# scheduled). Until that split exists, the conservative and unambiguous
# enforcement is: research and intelligence may not import `governance`
# at all. This will be narrowed (not widened) once a read-only governance
# accessor module exists — narrowing is a safe future change; the reverse
# would not be.

RULES: tuple[ForbiddenImportRule, ...] = (
    # --- Research isolation (Stage 2 §11/§16, Stage 3 §14/§17/§20) -------
    ForbiddenImportRule(
        source_package="research",
        forbidden_prefix="risk_execution",
        rationale=(
            "RR-9 / Stage 2 ADR-2: self-improvement and research experiments must "
            "never have a write (or any) path to the risk/execution plane. This is "
            "the single most safety-critical rule in the system — it is what makes "
            "'a self-improving mechanism cannot erode a risk constraint' a structural "
            "fact rather than a policy."
        ),
    ),
    ForbiddenImportRule(
        source_package="research",
        forbidden_prefix="governance",
        rationale=(
            "Stage 2 §16 / AR-2: research must never be able to write operator "
            "config, autonomy level, or kill-switch state (no self-promotion path). "
            "See module docstring note on 'governance write interfaces'."
        ),
    ),
    ForbiddenImportRule(
        source_package="research",
        forbidden_prefix="observability.decision_log",
        rationale=(
            "Stage 3 §3.5: Research reads historical data via Plane 1's normalization "
            "output and its own experiment store only; it must not write into the "
            "live decision-log store, which is Plane 1/4's append-only audit trail."
        ),
    ),
    # --- Intelligence (Plane 2) isolation (Stage 2 §4/§8/§9, Stage 3 §13/§17) -
    ForbiddenImportRule(
        source_package="intelligence",
        forbidden_prefix="risk_execution",
        rationale=(
            "TR-3 / Stage 2 §9: Plane 2 must never have execution authority or any "
            "path to the broker/risk engine other than the CandidateTrade interface "
            "boundary (domain.models). Sizing, order placement, and credentials are "
            "Plane 3's alone."
        ),
    ),
    ForbiddenImportRule(
        source_package="intelligence",
        forbidden_prefix="governance",
        rationale=(
            "Stage 3 §3.1: Plane 2 is stateless with respect to governance and never "
            "queries Plane 0 directly; the permitted universe is passed through Plane 1."
        ),
    ),
    ForbiddenImportRule(
        source_package="intelligence",
        forbidden_prefix="data.adapters",
        rationale=(
            "Stage 2 §7 'data flow principle' / Stage 3 §5: no Plane 2 implementation "
            "may open its own parallel, unvalidated ingestion path. Plane 2 may only "
            "consume Plane 1's normalized FeatureSnapshot output (data.features)."
        ),
    ),
    # --- Plane 3 must not depend on Plane 2 internals (Stage 3 §7 note) ---
    ForbiddenImportRule(
        source_package="risk_execution",
        forbidden_prefix="intelligence",
        rationale=(
            "Stage 3 §7: Plane 3 must not depend on intelligence implementation "
            "details in a way that would let the intelligence layer bypass the "
            "CandidateTrade boundary. Plane 3 only ever sees a domain.models.CandidateTrade "
            "instance; it has no reason to import anything from `intelligence` at all."
        ),
    ),
)


def rules_for_owning_package(owning_package: str) -> tuple[ForbiddenImportRule, ...]:
    """Return every rule whose source_package covers `owning_package`."""
    return tuple(r for r in RULES if r.applies_to_owning_package(owning_package))


# Cumulative Slice 2–4 rules. Domain may use pure shared time/ID utilities.
RULES += tuple(
    ForbiddenImportRule(source, target, "Cumulative plane isolation, Slices 1–4")
    for source, targets in {
        "domain": [
            "data",
            "intelligence",
            "risk_execution",
            "observability",
            "research",
            "governance",
        ],
        "intelligence": [
            "risk_execution",
            "research",
            "observability",
            "governance",
            "data.adapters",
            "data.normalization",
            "risk_execution",
            "research",
            "governance",
        ],
        "research": [
            "risk_execution",
            "governance",
            "risk_execution",
            "governance",
            "data.adapters",
        ],
        "governance": ["intelligence", "research", "data.adapters"],
        "data": ["intelligence", "risk_execution", "research"],
        "shared": ["intelligence", "research", "risk_execution.broker"],
    }.items()
    for target in sorted(set(targets))
    if not any(r.source_package == source and r.forbidden_prefix == target for r in RULES)
)


# ---------------------------------------------------------------------------
# Slice 6 additions — execution-safe research pipeline
# ---------------------------------------------------------------------------
# `simulation` is the offline orchestrator that wires
#   strategy -> risk -> sizing -> simulated broker -> portfolio.
# It exists as its own package because the Slice 5 rule `research -X-> risk_execution`
# (Stage 2 §11/§16) must stay intact: the research environment itself may never
# reach execution code, so the one component that legitimately touches both lives
# outside both. Nothing may import it (it is a leaf), and it may not import any
# concrete strategy or any data adapter: it is strategy-agnostic by construction.
_S6 = "Slice 6 / Stage 3 §7-§10, §17, ADR-8: "


def _r(src: str, forbidden: str, why: str) -> ForbiddenImportRule:
    return ForbiddenImportRule(source_package=src, forbidden_prefix=forbidden, rationale=_S6 + why)


_SLICE6_RULES: tuple[ForbiddenImportRule, ...] = (
    # nobody may depend on the orchestrator (leaf package)
    *(
        _r(src, "simulation", "simulation is a leaf orchestrator; no plane may depend on it")
        for src in (
            "domain", "data", "intelligence", "risk_execution", "observability",
            "research", "shared", "governance",
        )
    ),
    # orchestrator is strategy-agnostic and adapter-free
    _r("simulation", "intelligence.baseline", "runner must not know concrete strategies"),
    _r("simulation", "intelligence.llm_component", "no LLM in the execution pipeline"),
    _r("simulation", "data.adapters", "runner consumes canonical MarketData only"),
    _r("simulation", "governance", "no governance access from the research pipeline"),
    # Risk Engine independence (§15): no research, no orchestration, no adapters
    _r("risk_execution", "research", "Plane 3 must not depend on the research environment"),
    _r("risk_execution", "data.adapters", "Plane 3 must not touch data sources"),
    _r("risk_execution.risk_engine", "risk_execution.sizing", "risk must not depend on sizing"),
    _r("risk_execution.risk_engine", "risk_execution.broker", "risk must not depend on broker"),
    # Sizing independence (§21)
    _r("risk_execution.sizing", "risk_execution.broker", "sizing must not depend on broker"),
    _r("risk_execution.sizing", "risk_execution.risk_engine", "sizing consumes a RiskDecision only"),
    # Simulated broker independence (§38)
    _r("risk_execution.broker", "risk_execution.risk_engine", "broker must not import risk logic"),
    _r("risk_execution.broker", "risk_execution.sizing", "broker must not import sizing logic"),
)

RULES = RULES + _SLICE6_RULES


# ---------------------------------------------------------------------------
# Slice 7 additions — order lifecycle & reconciliation (ADR-10)
# ---------------------------------------------------------------------------
# Lifecycle/reconciliation consume only domain objects and broker *interface* types. They can never
# import risk logic or sizing (so they cannot manufacture approvals or OrderRequests), research,
# the orchestrator, strategies or data adapters; and risk/sizing/broker may not depend on them.
_S7 = "Slice 7 / ADR-10: "
_SLICE7_RULES: tuple[ForbiddenImportRule, ...] = tuple(
    ForbiddenImportRule(src, target, _S7 + why)
    for src in ("risk_execution.order_lifecycle", "risk_execution.reconciliation")
    for target, why in (
        ("risk_execution.risk_engine", "must not manufacture approvals"),
        ("risk_execution.sizing", "only sizing creates OrderRequests"),
        ("research", "execution never depends on research"),
        ("simulation", "orchestrator is a leaf"),
        ("intelligence", "no strategy/LLM access"),
        ("governance", "no governance access"),
        ("data.adapters", "no data sources"),
    )
) + tuple(
    ForbiddenImportRule(src, target, _S7 + "risk/sizing/broker stay independent of lifecycle bookkeeping")
    for src in ("risk_execution.risk_engine", "risk_execution.sizing", "risk_execution.broker")
    for target in ("risk_execution.order_lifecycle", "risk_execution.reconciliation")
) + (
    ForbiddenImportRule("risk_execution.order_lifecycle", "risk_execution.reconciliation",
                        _S7 + "reconciliation reads the lifecycle, never the reverse"),
)
RULES = RULES + _SLICE7_RULES
