"""Append-only, hash-chained trial ledger (Slice 9, ADR-15).

Every attempted trial is recorded — completed, failed, invalid, rejected, interrupted,
unsupported, worse-than-baseline or excluded. There is no delete/update API. Each line
embeds the previous line's hash, so removing or editing a middle entry is detectable by
`verify()`. Truncation of the tail is only detectable against an externally recorded
`head_hash()` (reports embed it).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from research.harness.jsonio import jsonable
from shared.time.clock import ensure_utc, utc_now
from shared.versioning.content_hash import hash_json_stable

GENESIS = "GENESIS"


class TrialOutcome(str, Enum):  # noqa: UP042
    COMPLETED = "COMPLETED"
    COMPLETED_WORSE_THAN_BASELINE = "COMPLETED_WORSE_THAN_BASELINE"
    FAILED = "FAILED"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    REJECTED = "REJECTED"
    INTERRUPTED = "INTERRUPTED"
    STARTED = "STARTED"  # write-ahead attempt-start event; never a terminal outcome
    UNSUPPORTED = "UNSUPPORTED"
    EXCLUDED_VALIDITY_FAILURE = "EXCLUDED_VALIDITY_FAILURE"


class TrialLedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrialEntry:
    trial_id: str
    sequence: int
    protocol_id: str
    protocol_hash: str | None
    run_id: str | None
    parent_trial_id: str | None
    strategy_id: str
    parameters: dict
    dataset_hash: str | None
    window: str | None
    universe: str | None
    cost_schedule_version: str | None
    mode: str  # EXPLORATORY | CONFIRMATORY
    outcome: TrialOutcome
    reason: str | None
    holdout_id: str | None
    holdout_exposed: bool
    holdout_reused: bool
    artifact_refs: dict
    recorded_at: datetime
    prev_hash: str
    entry_hash: str
    lifecycle: str | None = None  # "START" | "TERMINAL" | None (legacy single-event trial)
    attempt_id: str | None = None  # groups the lifecycle events of ONE logical trial


TERMINAL_OUTCOMES = frozenset(TrialOutcome) - {TrialOutcome.STARTED}


class TrialLedger:
    def __init__(self, root: Path | str, clock: Callable[[], datetime] = utc_now) -> None:
        self._dir = Path(root) / "trials"
        self._path = self._dir / "ledger.jsonl"
        self._clock = clock

    # ------------------------------------------------------------------ write
    def record(
        self, *, protocol_id: str, protocol_hash: str | None, strategy_id: str, mode: str,
        outcome: TrialOutcome, run_id: str | None = None, parent_trial_id: str | None = None,
        parameters: dict | None = None, dataset_hash: str | None = None,
        window: str | None = None, universe: str | None = None,
        cost_schedule_version: str | None = None, reason: str | None = None,
        holdout_id: str | None = None, holdout_exposed: bool = False,
        holdout_reused: bool = False, artifact_refs: dict | None = None,
        lifecycle: str | None = None, attempt_id: str | None = None,
    ) -> TrialEntry:  # fmt: skip
        if lifecycle not in (None, "START", "TERMINAL"):
            raise TrialLedgerError("lifecycle must be START, TERMINAL or None")
        if (lifecycle is None) != (attempt_id is None):
            raise TrialLedgerError("lifecycle and attempt_id must be given together")
        if (lifecycle == "START") != (outcome is TrialOutcome.STARTED):
            raise TrialLedgerError("START events use outcome STARTED and only they do")
        if lifecycle == "TERMINAL" and not any(
            e.attempt_id == attempt_id and e.lifecycle == "START" for e in self.entries()
        ):
            raise TrialLedgerError(f"terminal event for unknown attempt {attempt_id!r}")
        if lifecycle == "TERMINAL" and any(
            e.attempt_id == attempt_id and e.lifecycle == "TERMINAL" for e in self.entries()
        ):
            raise TrialLedgerError(f"attempt {attempt_id!r} already has a terminal outcome")
        if (
            outcome
            not in (
                TrialOutcome.COMPLETED,
                TrialOutcome.COMPLETED_WORSE_THAN_BASELINE,
                TrialOutcome.STARTED,
            )
            and not reason
        ):
            raise TrialLedgerError(f"outcome {outcome.value} requires a controlled reason")
        existing = self.entries()
        seq = len(existing) + 1
        prev = existing[-1].entry_hash if existing else GENESIS
        body = {
            "sequence": seq,
            "protocol_id": protocol_id,
            "protocol_hash": protocol_hash,
            "run_id": run_id,
            "parent_trial_id": parent_trial_id,
            "strategy_id": strategy_id,
            "parameters": jsonable(parameters or {}),
            "dataset_hash": dataset_hash,
            "window": window,
            "universe": universe,
            "cost_schedule_version": cost_schedule_version,
            "mode": mode,
            "outcome": outcome.value,
            "reason": reason,
            "holdout_id": holdout_id,
            "holdout_exposed": holdout_exposed,
            "holdout_reused": holdout_reused,
            "artifact_refs": jsonable(artifact_refs or {}),
            "prev_hash": prev,
        }
        if lifecycle is not None:  # added only when used, so legacy line hashes are unchanged
            body["lifecycle"] = lifecycle
            body["attempt_id"] = attempt_id
        h = hash_json_stable(body)
        trial_id = f"trial_{seq:06d}_{h[:12]}"
        at = ensure_utc(self._clock())
        line = {"trial_id": trial_id, **body, "recorded_at": at.isoformat(), "entry_hash": h}
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return self._to_entry(line)

    # ------------------------------------------------------------------- read
    @staticmethod
    def _to_entry(d: dict) -> TrialEntry:
        return TrialEntry(
            trial_id=d["trial_id"], sequence=d["sequence"], protocol_id=d["protocol_id"],
            protocol_hash=d["protocol_hash"], run_id=d["run_id"],
            parent_trial_id=d["parent_trial_id"], strategy_id=d["strategy_id"],
            parameters=d["parameters"], dataset_hash=d["dataset_hash"], window=d["window"],
            universe=d["universe"], cost_schedule_version=d["cost_schedule_version"],
            mode=d["mode"], outcome=TrialOutcome(d["outcome"]), reason=d["reason"],
            holdout_id=d["holdout_id"], holdout_exposed=d["holdout_exposed"],
            holdout_reused=d["holdout_reused"], artifact_refs=d["artifact_refs"],
            recorded_at=datetime.fromisoformat(d["recorded_at"]), prev_hash=d["prev_hash"],
            entry_hash=d["entry_hash"], lifecycle=d.get("lifecycle"), attempt_id=d.get("attempt_id"),
        )  # fmt: skip

    def entries(self) -> list[TrialEntry]:
        if not self._path.exists():
            return []
        out = []
        for ln in self._path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                out.append(self._to_entry(json.loads(ln)))
        return out

    def head_hash(self) -> str:
        e = self.entries()
        return e[-1].entry_hash if e else GENESIS

    def verify(self) -> list[str]:
        """Return chain problems (empty list = intact)."""
        problems: list[str] = []
        prev = GENESIS
        if not self._path.exists():
            return problems
        for i, ln in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not ln.strip():
                continue
            d = json.loads(ln)
            body = {
                k: v for k, v in d.items() if k not in ("trial_id", "recorded_at", "entry_hash")
            }
            if d["sequence"] != i:
                problems.append(
                    f"line {i}: sequence {d['sequence']} (an entry was removed/reordered)"
                )
            if d["prev_hash"] != prev:
                problems.append(f"line {i}: prev_hash mismatch (chain broken)")
            if hash_json_stable(body) != d["entry_hash"]:
                problems.append(f"line {i}: entry content does not match its hash")
            prev = d["entry_hash"]
        return problems

    # ---------------------------------------------------------- logical trials
    def logical_trials(self, *, protocol_id: str | None = None) -> list[TrialEntry]:
        """One entry per LOGICAL trial: the latest lifecycle event of each attempt, plus every
        legacy single-event entry. Denominator for all reported trial counts (see docs)."""
        latest: dict[str, TrialEntry] = {}
        out: list[TrialEntry] = []
        order: list[str] = []
        for e in self.entries():
            if protocol_id is not None and e.protocol_id != protocol_id:
                continue
            if e.attempt_id is None:
                out.append(e)
            else:
                if e.attempt_id not in latest:
                    order.append(e.attempt_id)
                latest[e.attempt_id] = e
        return sorted(out + [latest[a] for a in order], key=lambda e: e.sequence)

    def unresolved(self, *, protocol_id: str | None = None) -> list[TrialEntry]:
        """Attempts whose latest event is STARTED: crashed/interrupted/unfinished."""
        return [
            e
            for e in self.logical_trials(protocol_id=protocol_id)
            if e.outcome is TrialOutcome.STARTED
        ]

    def recover_unresolved(self, reason: str) -> list[TrialEntry]:
        """Classify every unfinished attempt as INTERRUPTED. Never fabricates results."""
        out = []
        for e in self.unresolved():
            out.append(self.record(
                protocol_id=e.protocol_id, protocol_hash=e.protocol_hash, strategy_id=e.strategy_id,
                mode=e.mode, outcome=TrialOutcome.INTERRUPTED, reason=reason, lifecycle="TERMINAL",
                attempt_id=e.attempt_id, parameters=e.parameters, holdout_id=e.holdout_id,
                holdout_exposed=e.holdout_exposed,
            ))  # fmt: skip
        return out

    def event_count(self) -> int:
        return len(self.entries())

    def count(self, *, protocol_id: str | None = None, strategy_id: str | None = None,
              mode: str | None = None) -> int:  # fmt: skip
        """Number of LOGICAL trials (not lifecycle events)."""
        return len([e for e in self.logical_trials(protocol_id=protocol_id)
                    if (strategy_id is None or e.strategy_id == strategy_id)
                    and (mode is None or e.mode == mode)])  # fmt: skip

    def select(self, *, protocol_id: str | None = None, strategy_id: str | None = None,
               mode: str | None = None, outcome: TrialOutcome | None = None) -> list[TrialEntry]:  # fmt: skip
        return [
            e for e in self.entries()
            if (protocol_id is None or e.protocol_id == protocol_id)
            and (strategy_id is None or e.strategy_id == strategy_id)
            and (mode is None or e.mode == mode)
            and (outcome is None or e.outcome is outcome)
        ]  # fmt: skip
