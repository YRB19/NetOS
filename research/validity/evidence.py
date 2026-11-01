"""Verifiable evaluation evidence (Slice 9 closure, ADR-20).

`EvaluationEvidence` is a *pointer* record issued by `ResearchEvaluationService`. It carries
no trusted facts: `verify()` re-derives every fact a confirmatory report needs from the
durable stores (protocol registry, trial ledger, holdout registry, run artifacts). A
fabricated or stale evidence object therefore fails verification instead of granting status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from research.protocol.protocol import ExperimentProtocol
from research.protocol.registry import ProtocolError, ProtocolNotRegistered, ProtocolRegistry
from research.trials.holdout import HoldoutRegistry
from research.trials.ledger import TrialLedger, TrialOutcome
from shared.time.clock import ensure_utc


@dataclass(frozen=True)
class EvaluationEvidence:
    root: str
    attempt_id: str
    protocol_id: str
    protocol_version: int
    protocol_hash: str
    evaluation_started_at: datetime
    holdout_id: str
    exposure_recorded: bool
    dataset_hash: str
    effective_confirmatory: bool  # the service's decision; re-checked, never trusted alone
    downgrade_reasons: tuple[str, ...] = ()
    run_id: str | None = None
    run_artifact_digest: str | None = None

    def verify(self, protocol: ExperimentProtocol) -> dict:
        from research.validity.evaluation import ReproducibilityFailure, verify_stored_run  # noqa: PLC0415

        root = Path(self.root)
        problems: list[str] = []
        out: dict = {"ok": False, "problems": problems, "ledger_chain_ok": False}
        # protocol identity + pre-registration
        registered_at = None
        try:
            reg = ProtocolRegistry(root).get(self.protocol_id, self.protocol_version)
            registered_at = reg.registered_at
            if not (reg.protocol_hash == self.protocol_hash == protocol.protocol_hash()):
                problems.append(
                    "PROTOCOL_HASH_MISMATCH: supplied protocol differs from the registered one"
                )
        except (ProtocolNotRegistered, ProtocolError) as e:
            problems.append(f"PROTOCOL_NOT_VERIFIED: {e}")
        out["protocol_registered_at"] = registered_at.isoformat() if registered_at else None
        # ledger
        led = TrialLedger(root)
        chain = led.verify()
        out["ledger_chain_ok"] = not chain
        problems += [f"LEDGER_CORRUPT: {c}" for c in chain]
        entries = [e for e in led.entries() if e.attempt_id == self.attempt_id]
        start = next((e for e in entries if e.lifecycle == "START"), None)
        term = next((e for e in entries if e.lifecycle == "TERMINAL"), None)
        if start is None:
            problems.append("ATTEMPT_NOT_IN_LEDGER: no START record (no write-ahead evidence)")
        else:
            if ensure_utc(start.recorded_at) != ensure_utc(self.evaluation_started_at):
                problems.append(
                    "EVALUATION_START_MISMATCH: evidence start time differs from the ledger START record"
                )
            if start.protocol_hash != self.protocol_hash:
                problems.append("ATTEMPT_PROTOCOL_MISMATCH")
            if registered_at is not None and ensure_utc(registered_at) > ensure_utc(
                start.recorded_at
            ):
                problems.append("PROTOCOL_REGISTERED_AFTER_EVALUATION_START")
        if term is None:
            problems.append("ATTEMPT_UNRESOLVED: no terminal outcome recorded")
        out["terminal_outcome"] = term.outcome.value if term else None
        # holdout
        hr = HoldoutRegistry(root)
        if self.exposure_recorded:
            rec = next(
                (r for r in hr.exposures(self.holdout_id) if r["run_id"] == self.attempt_id), None
            )
            if rec is None:
                problems.append("HOLDOUT_EXPOSURE_NOT_RECORDED")
                out["holdout_status"], out["holdout_exposure_number"] = "UNVERIFIED", None
            else:
                out["holdout_status"] = rec["status_at_exposure"]
                out["holdout_exposure_number"] = rec["exposure_number"]
                if rec["status_at_exposure"] == "UNTOUCHED" and rec["exposure_number"] != 1:
                    problems.append("HOLDOUT_STATUS_INCONSISTENT")
        else:
            out["holdout_status"], out["holdout_exposure_number"] = "NOT_EXPOSED", None
        # trial accounting derived from the verified ledger
        logical = led.logical_trials(protocol_id=self.protocol_id)
        by: dict[str, int] = {}
        for e in logical:
            by[e.outcome.value] = by.get(e.outcome.value, 0) + 1
        out.update(
            trial_count=len(logical),
            trials_by_outcome=by,
            unresolved_count=sum(1 for e in logical if e.outcome is TrialOutcome.STARTED),
            event_count=led.event_count(),
            ledger_head_hash=led.head_hash(),
            trial_denominator=(
                "logical trials with protocol_id == this protocol family (all versions): one per attempt_id "
                "(latest lifecycle event) plus each legacy single-event entry; lifecycle events are not counted separately"
            ),  # fmt: skip
        )
        # run artifact
        if self.run_id and self.run_artifact_digest:
            try:
                verify_stored_run(root, self.run_id, self.run_artifact_digest)
                out["run_artifact_verified"] = True
            except ReproducibilityFailure as e:
                problems.append(f"RUN_ARTIFACT_NOT_VERIFIED: {e}")
                out["run_artifact_verified"] = False
        else:
            out["run_artifact_verified"] = False
        out["ok"] = not problems
        return out
