"""ResearchEvaluationService — the single enforced entry point for evaluations (ADR-20).

Orchestrates the existing registries and harness; it does not replace any of them and does
not touch strategy, execution, risk, sizing, cost or portfolio logic. A *confirmatory*
evaluation runs only when the complete contract holds; otherwise it is rejected before
the harness runs (recorded in the trial ledger) or downgraded to non-confirmatory.
Independent helper APIs (`build_report`, registries used directly) remain available but
cannot grant confirmatory status.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from data.features.context_builder import compute_market_data_snapshot_version
from data.features.universe import PermittedUniverse
from domain.models.market_data import MarketData
from research.contamination.point_in_time import AvailabilityLedger
from research.experiments.store import _files_for, content_digest, write_run
from research.harness.config import EvaluationPeriod, ResearchConfig
from research.harness.failures import FailureCategory
from research.harness.result import ResearchRunResult
from research.harness.runner import ResearchHarness
from research.protocol.protocol import ExperimentMode, ExperimentProtocol, HoldoutReusePolicy
from research.protocol.registry import ProtocolError, ProtocolRegistry
from research.splits.plan import validate_split_with_horizon
from research.stats.pbo import compute_pbo
from research.stats.regimes import RegimeDefinition, classify, equal_weight_index, segment_equity
from research.trials.holdout import HoldoutRegistry, HoldoutReuseError, holdout_id_for
from research.trials.ledger import TrialLedger, TrialOutcome
from research.validity.assumptions import ExecutionAssumptions
from research.validity.evaluation import build_verified_report, write_report
from research.validity.evidence import EvaluationEvidence
from research.validity.metrics import compute_extended_metrics, final_marks_from_market_data
from research.validity.quality import DatasetProvenance, assess_quality
from shared.costs import CostModel
from shared.time.clock import ensure_utc, utc_now
from shared.versioning.content_hash import hash_json_stable


def compute_dataset_hash(
    market_data: list[MarketData], availability: AvailabilityLedger | None = None
) -> str:
    """Same identity the harness records as `data_snapshot_version`."""
    v = compute_market_data_snapshot_version(list(market_data))
    if availability is not None:
        v = "pit_" + hash_json_stable([v, availability.fingerprint()])[:32]
    return v


@dataclass(frozen=True)
class EvaluationOutcome:
    status: str  # REJECTED_PREFLIGHT | COMPLETED | FAILED
    attempt_id: str
    reasons: tuple[str, ...]
    result: ResearchRunResult | None = None
    evidence: EvaluationEvidence | None = None
    report: dict | None = None
    report_path: Path | None = None


class ResearchEvaluationService:
    def __init__(self, root: Path | str, clock: Callable[[], datetime] = utc_now,
                 harness_factory: Callable[[AvailabilityLedger | None], ResearchHarness] | None = None) -> None:  # fmt: skip
        self.root = Path(root)
        self._clock = clock
        self.protocols = ProtocolRegistry(self.root, clock)
        self.ledger = TrialLedger(self.root, clock)
        self.holdouts = HoldoutRegistry(self.root, clock)
        self._harness_factory = harness_factory or (lambda av: ResearchHarness(availability=av))

    def recover_interrupted(
        self, reason: str = "unfinished attempt found on reopen; no result exists"
    ) -> int:
        """Explicitly classify unfinished attempts as INTERRUPTED (appends; never edits)."""
        return len(self.ledger.recover_unresolved(reason))

    # ------------------------------------------------------------------ helpers
    def _preflight(self, protocol, config, strategy, market_data, universe_schedule, provenance,
                   baseline_ids, dataset_hash, holdout_id, started_at) -> list[str]:  # fmt: skip
        bad: list[str] = []
        try:
            self.protocols.verify_registered_before(protocol, started_at)
        except ProtocolError as e:
            bad.append(f"PROTOCOL: {e}")
        errs = protocol.validate()
        bad += [f"PROTOCOL_INVALID: {e}" for e in errs]
        if config.hypothesis != protocol.hypothesis:
            bad.append("MISMATCH hypothesis")
        if config.split != protocol.split:
            bad.append("MISMATCH split")
        if config.evaluation_period is not EvaluationPeriod.OUT_OF_SAMPLE:
            bad.append("MISMATCH evaluation_period must be OUT_OF_SAMPLE for a confirmatory run")
        if config.cost_schedule_version != protocol.cost_schedule_version:
            bad.append("MISMATCH cost_schedule_version")
        if config.strategy_configured_through != protocol.strategy_configured_through:
            bad.append("MISMATCH strategy_configured_through")
        if protocol.execution_assumptions.get("fill") != config.execution_assumption:
            bad.append("MISMATCH execution_assumption (protocol must declare 'fill')")
        sid = str(getattr(strategy, "strategy_version_id", ""))
        if sid not in protocol.strategy_version_ids:
            bad.append(f"MISMATCH strategy_version_id {sid!r} not in protocol")
        if not baseline_ids or not set(baseline_ids) <= set(protocol.benchmark_version_ids):
            bad.append(
                "MISMATCH baseline ids must be supplied and be a subset of the protocol benchmarks"
            )
        if {u.version for u in universe_schedule} != set(protocol.universe_versions):
            bad.append("MISMATCH universe versions")
        if market_data and (
            min(m.timestamp for m in market_data) < protocol.data_start
            or max(m.timestamp for m in market_data) > protocol.data_end
        ):
            bad.append("MISMATCH market data outside the protocol date range")
        if protocol.dataset_version != dataset_hash:
            bad.append("MISMATCH dataset_version is not the supplied dataset's hash")
        if provenance.dataset_id != protocol.dataset_id:
            bad.append("MISMATCH dataset_id")
        if holdout_id != protocol.holdout_id:
            bad.append("MISMATCH holdout_id (derived from dataset hash, universes and test window)")
        chain = self.ledger.verify()
        bad += [f"LEDGER_CORRUPT: {c}" for c in chain]
        return bad

    # ------------------------------------------------------------------- main
    def evaluate(self, *, protocol: ExperimentProtocol, config: ResearchConfig, strategy,
                 market_data: list[MarketData], universe_schedule: list[PermittedUniverse],
                 provenance: DatasetProvenance, availability: AvailabilityLedger | None = None,
                 baseline_ids: tuple[str, ...] | None = None, baseline_result: ResearchRunResult | None = None,
                 assumptions: ExecutionAssumptions | None = None, regime: RegimeDefinition | None = None,
                 pbo_returns: dict | None = None, pbo_partitions: int = 8,
                 journal_refs: dict | None = None) -> EvaluationOutcome:  # fmt: skip
        started_at = ensure_utc(self._clock())
        p_hash = protocol.protocol_hash()
        confirmatory = protocol.mode is ExperimentMode.CONFIRMATORY
        mode = protocol.mode.value
        strategy_id = str(getattr(strategy, "strategy_version_id", "UNKNOWN_STRATEGY"))
        try:
            dataset_hash = compute_dataset_hash(market_data, availability)
        except Exception as e:  # noqa: BLE001 - invalid data is a recorded trial, not a lost exception
            dataset_hash = f"UNCOMPUTABLE:{type(e).__name__}"
        hid = holdout_id_for(dataset_id=protocol.dataset_id, dataset_hash=dataset_hash,
                             universe_versions=tuple(u.version for u in universe_schedule),
                             test_start=config.split.test_start, test_end=config.split.test_end)  # fmt: skip
        window = f"{config.split.test_start.isoformat()}..{config.split.test_end.isoformat()}"
        universe = ",".join(sorted(u.version for u in universe_schedule))
        base_kw = dict(protocol_id=protocol.protocol_id, protocol_hash=p_hash, strategy_id=strategy_id,
                       mode=mode, dataset_hash=dataset_hash, window=window, universe=universe,
                       cost_schedule_version=config.cost_schedule_version, holdout_id=hid)  # fmt: skip
        # write-ahead START (durable before anything else happens)
        attempt_id = (
            "attempt_"
            + hash_json_stable([p_hash, started_at.isoformat(), self.ledger.head_hash()])[:24]
        )
        self.ledger.record(
            outcome=TrialOutcome.STARTED, lifecycle="START", attempt_id=attempt_id, **base_kw
        )
        # the ledger START's recorded_at is the authoritative evaluation start time
        start_entry = next(
            e
            for e in self.ledger.entries()
            if e.attempt_id == attempt_id and e.lifecycle == "START"
        )
        started_at = ensure_utc(start_entry.recorded_at)

        problems = self._preflight(protocol, config, strategy, market_data, universe_schedule, provenance,
                                   baseline_ids, dataset_hash, hid, started_at)  # fmt: skip
        downgrade: list[str] = []
        if problems:
            if confirmatory:
                self.ledger.record(outcome=TrialOutcome.REJECTED, lifecycle="TERMINAL", attempt_id=attempt_id,
                                   reason="; ".join(problems)[:1000], **base_kw)  # fmt: skip
                return EvaluationOutcome("REJECTED_PREFLIGHT", attempt_id, tuple(problems))
            downgrade += [f"exploratory run with unverified correspondence: {p}" for p in problems]
        # holdout exposure (any run that evaluates the out-of-sample window exposes it)
        exposed, holdout_status = False, "NOT_EXPOSED"
        if config.evaluation_period is EvaluationPeriod.OUT_OF_SAMPLE:
            policy = (
                protocol.holdout_reuse_policy
                if confirmatory
                else HoldoutReusePolicy.DOWNGRADE_TO_NON_CONFIRMATORY
            )
            try:
                holdout_status = self.holdouts.expose(holdout_id=hid, protocol_id=protocol.protocol_id,
                                                      protocol_hash=p_hash, run_id=attempt_id, mode=mode, policy=policy).value  # fmt: skip
            except HoldoutReuseError as e:
                self.ledger.record(outcome=TrialOutcome.REJECTED, lifecycle="TERMINAL", attempt_id=attempt_id,
                                   reason=str(e), holdout_reused=True, **base_kw)  # fmt: skip
                return EvaluationOutcome("REJECTED_PREFLIGHT", attempt_id, (str(e),))
            exposed = True
            if holdout_status != "UNTOUCHED":
                downgrade.append("holdout previously exposed: reuse is non-confirmatory")
        harness = self._harness_factory(availability)
        try:
            result = harness.run(config, strategy, market_data, universe_schedule, baseline_ids)
        except BaseException as e:
            if isinstance(e, Exception):
                self.ledger.record(outcome=TrialOutcome.FAILED, lifecycle="TERMINAL", attempt_id=attempt_id,
                                   reason=f"unhandled {type(e).__name__}: {e}"[:500], holdout_exposed=exposed, **base_kw)  # fmt: skip
                return EvaluationOutcome("FAILED", attempt_id, (f"unhandled {type(e).__name__}",))
            self.ledger.record(outcome=TrialOutcome.INTERRUPTED, lifecycle="TERMINAL", attempt_id=attempt_id,
                               reason=f"interrupted by {type(e).__name__}", holdout_exposed=exposed, **base_kw)  # fmt: skip
            raise
        write_run(result, self.root)  # failure artifacts are preserved too
        digest = content_digest(_files_for(result))
        # post-run correspondence
        post: list[str] = []
        if result.data_snapshot_version != dataset_hash:
            post.append(
                "MISMATCH run data_snapshot_version differs from the evaluated dataset hash"
            )
        if result.strategy_version_id not in protocol.strategy_version_ids:
            post.append("MISMATCH run strategy_version_id not in protocol")
        if not set(result.baseline_strategy_version_ids) <= set(protocol.benchmark_version_ids):
            post.append("MISMATCH run baselines not in protocol benchmarks")
        if {v for v, _ in result.universe_schedule} != set(protocol.universe_versions):
            post.append("MISMATCH run universe versions")
        if post and confirmatory:
            downgrade += post
        # terminal outcome
        if not result.succeeded:
            cat = result.failure.category if result.failure else None
            outcome = (TrialOutcome.INVALID_CONFIGURATION if cat is FailureCategory.INVALID_CONFIGURATION
                       else TrialOutcome.EXCLUDED_VALIDITY_FAILURE if cat is FailureCategory.CONTAMINATION
                       else TrialOutcome.FAILED)  # fmt: skip
            reason = result.failure.message if result.failure else "run failed"
        elif post and confirmatory:
            outcome, reason = TrialOutcome.EXCLUDED_VALIDITY_FAILURE, "; ".join(post)
        else:
            outcome, reason = TrialOutcome.COMPLETED, None
            if (baseline_result is not None and baseline_result.metrics is not None and result.metrics is not None
                    and baseline_result.comparison_fingerprint == result.comparison_fingerprint
                    and Decimal(result.metrics["total_return"]) < Decimal(baseline_result.metrics["total_return"])):  # fmt: skip
                outcome = TrialOutcome.COMPLETED_WORSE_THAN_BASELINE
        self.ledger.record(outcome=outcome, lifecycle="TERMINAL", attempt_id=attempt_id, reason=reason, run_id=result.run_id,
                           holdout_exposed=exposed, holdout_reused=holdout_status == "REUSED_NON_CONFIRMATORY",
                           artifact_refs={"run_id": result.run_id, "run_artifact_digest": digest}, **base_kw)  # fmt: skip
        evidence = EvaluationEvidence(
            root=str(self.root), attempt_id=attempt_id, protocol_id=protocol.protocol_id, protocol_version=protocol.version,
            protocol_hash=p_hash, evaluation_started_at=started_at, holdout_id=hid, exposure_recorded=exposed,
            dataset_hash=dataset_hash, effective_confirmatory=confirmatory and not downgrade,
            downgrade_reasons=tuple(downgrade), run_id=result.run_id, run_artifact_digest=digest)  # fmt: skip
        # analytics (only meaningful for a completed run)
        quality = assess_quality(market_data, universe_schedule, provenance)
        metrics = (compute_extended_metrics(
            result, cost_model=CostModel(), final_marks=final_marks_from_market_data(result, market_data),
            assumptions=assumptions, baseline=baseline_result,
            unique_trial_count=self.ledger.count(protocol_id=protocol.protocol_id)) if result.succeeded
            else {"status": "UNAVAILABLE", "reason": "run did not complete"})  # fmt: skip
        regimes = None
        if regime is not None and result.succeeded:
            idx = equal_weight_index(
                market_data, {i for u in universe_schedule for i in u.instrument_ids}
            )
            regimes = segment_equity(list(result.equity_curve), classify(idx, regime), regime)
        pbo = compute_pbo(pbo_returns, pbo_partitions).to_dict() if pbo_returns else None
        try:
            purge = validate_split_with_horizon(protocol.split, protocol.information_horizon_days,
                                                protocol.embargo_days or 0, protocol.links.get("information_horizon_justification"))  # fmt: skip
        except ValueError as e:
            purge = {"split": {"status": "NOT_DECLARED", "reason": str(e)}}
        report = build_verified_report(evidence=evidence, protocol=protocol, result=result, extended_metrics=metrics,
                                       quality=quality, pbo=pbo, regimes=regimes, purge=purge, journal_refs=journal_refs)  # fmt: skip
        path = write_report(report, self.root, attempt_id)
        return EvaluationOutcome("COMPLETED" if result.succeeded else "FAILED", attempt_id, tuple(downgrade),
                                 result, evidence, report, path)  # fmt: skip
