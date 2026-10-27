"""Chronological walk-forward plans, purge and embargo (Slice 9, ADR-17).

Conventions (documented in docs/statistical-validation.md):
* All windows are INCLUSIVE of both endpoints on timestamps, matching `window_bounds`.
* A training sample at time t has an outcome/information horizon of H days: it uses
  information up to t + H. It is PURGED if t + H + E >= test_start (E = embargo days).
  Equivalently samples are allowed iff t < test_start - (H + E) days.
* H = 0 is accepted only with a written justification; H = None means undeclared and the
  split is reported NOT_DECLARED (never silently assumed safe).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from domain.models.research_artifacts import SplitSpec
from research.harness.config import EvaluationPeriod, ResearchConfig, two_way_split
from research.harness.failures import ResearchRunFailure
from research.harness.result import ResearchRunResult
from shared.versioning.content_hash import hash_json_stable


class WalkForwardMode(str, Enum):  # noqa: UP042
    EXPANDING = "EXPANDING"
    ROLLING = "ROLLING"


@dataclass(frozen=True)
class PurgeReport:
    status: str  # APPLIED | NOT_REQUIRED_JUSTIFIED | NOT_DECLARED
    horizon_days: int | None
    embargo_days: int
    justification: str | None
    train_cutoff_exclusive: datetime  # train samples valid iff t < this
    declared_train_end: datetime
    excluded_interval: tuple[datetime, datetime] | None  # [cutoff, declared_train_end] inclusive
    gap_days_after_purge: float

    def to_dict(self) -> dict:
        return {
            "status": self.status, "horizon_days": self.horizon_days,
            "embargo_days": self.embargo_days, "justification": self.justification,
            "train_cutoff_exclusive": self.train_cutoff_exclusive.isoformat(),
            "declared_train_end": self.declared_train_end.isoformat(),
            "excluded_interval": [x.isoformat() for x in self.excluded_interval] if self.excluded_interval else None,
        }  # fmt: skip


def purge_boundary(train_end: datetime, test_start: datetime, horizon_days: int | None,
                   embargo_days: int = 0, justification: str | None = None) -> PurgeReport:  # fmt: skip
    if horizon_days is None:
        return PurgeReport("NOT_DECLARED", None, embargo_days, justification, train_end, train_end,
                           None, (test_start - train_end).total_seconds() / 86400)  # fmt: skip
    if horizon_days < 0 or embargo_days < 0:
        raise ValueError("horizon_days and embargo_days must be >= 0")
    if horizon_days == 0 and embargo_days == 0:
        if not justification:
            raise ValueError("horizon 0 / embargo 0 requires a written justification (no arbitrary gap, no silent skip)")
        status = "NOT_REQUIRED_JUSTIFIED"
    else:
        status = "APPLIED"
    cutoff = test_start - timedelta(days=horizon_days + embargo_days)
    excluded = (cutoff, train_end) if cutoff <= train_end else None
    return PurgeReport(status, horizon_days, embargo_days, justification, cutoff, train_end,
                       excluded, (test_start - train_end).total_seconds() / 86400)  # fmt: skip


def validate_split_with_horizon(split: SplitSpec, horizon_days: int | None, embargo_days: int = 0,
                                justification: str | None = None) -> dict:  # fmt: skip
    """Boundary-by-boundary purge report for a declared SplitSpec."""
    empty_val = split.validation_start == split.validation_end == split.train_end
    out = {"train_to_test" if empty_val else "train_to_validation": None}
    out = {}
    if empty_val:
        out["train_to_test"] = purge_boundary(split.train_end, split.test_start, horizon_days, embargo_days, justification).to_dict()
    else:
        out["train_to_validation"] = purge_boundary(split.train_end, split.validation_start, horizon_days, embargo_days, justification).to_dict()
        out["validation_to_test"] = purge_boundary(split.validation_end, split.test_start, horizon_days, embargo_days, justification).to_dict()
    return out


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    purge: PurgeReport
    earlier_test_windows_in_training: bool

    def to_dict(self) -> dict:
        return {
            "index": self.index, "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(), "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(), "purge": self.purge.to_dict(),
            "earlier_test_windows_in_training": self.earlier_test_windows_in_training,
        }  # fmt: skip


@dataclass(frozen=True)
class WalkForwardPlan:
    mode: WalkForwardMode
    data_start: datetime
    data_end: datetime
    initial_train_days: int
    test_days: int
    step_days: int
    horizon_days: int | None
    embargo_days: int = 0
    purge_justification: str | None = None
    rolling_train_days: int | None = None

    def windows(self) -> list[WalkForwardWindow]:
        for n, v in (("initial_train_days", self.initial_train_days), ("test_days", self.test_days), ("step_days", self.step_days)):
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ValueError(f"{n} must be a positive int")
        if self.mode is WalkForwardMode.ROLLING and not self.rolling_train_days:
            raise ValueError("ROLLING mode requires rolling_train_days")
        if self.data_start > self.data_end:
            raise ValueError("data_start after data_end")
        out: list[WalkForwardWindow] = []
        test_start = self.data_start + timedelta(days=self.initial_train_days)
        i = 0
        while True:
            test_end = test_start + timedelta(days=self.test_days) - timedelta(microseconds=1)
            if test_end > self.data_end:
                break
            train_end = test_start - timedelta(microseconds=1)
            if self.mode is WalkForwardMode.EXPANDING:
                train_start = self.data_start
            else:
                train_start = max(self.data_start, test_start - timedelta(days=self.rolling_train_days))  # type: ignore[arg-type]
            purge = purge_boundary(train_end, test_start, self.horizon_days, self.embargo_days, self.purge_justification)
            out.append(WalkForwardWindow(i, train_start, train_end, test_start, test_end, purge, i > 0))
            i += 1
            test_start = test_start + timedelta(days=self.step_days)
        # test windows must not overlap each other (OOS results are independent segments)
        for a, b in zip(out, out[1:], strict=False):
            if b.test_start <= a.test_end:
                raise ValueError("step_days < test_days: consecutive test windows would overlap")
        return out

    def plan_hash(self) -> str:
        return hash_json_stable({"plan": dataclasses.asdict(self), "windows": [w.to_dict() for w in self.windows()]})


@dataclass(frozen=True)
class WalkForwardOutcome:
    status: str  # COMPLETED | UNSUPPORTED | FAILED
    reason: str | None
    plan_hash: str | None
    window_results: tuple[dict, ...]
    refit: str  # NOT_APPLICABLE_FIXED_CONFIGURATION

    def to_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason, "plan_hash": self.plan_hash,
                "window_results": list(self.window_results), "refit": self.refit}  # fmt: skip


def run_walk_forward(harness, plan: WalkForwardPlan, base_config: ResearchConfig, strategy,
                     market_data, universe_schedule, refit_required: bool = False) -> WalkForwardOutcome:  # fmt: skip
    """Evaluate a FIXED-configuration strategy over sequential out-of-sample windows.

    Existing strategies (Tier-1, Tier-2) have no fit step, so no re-fitting happens and this
    is recorded explicitly. A strategy that needs re-fitting is UNSUPPORTED here (no safe
    re-fit contract exists yet) rather than evaluated misleadingly."""
    if refit_required:
        return WalkForwardOutcome("UNSUPPORTED", "per-window re-fitting is not supported by the current strategy contracts", None, (), "UNSUPPORTED")  # fmt: skip
    try:
        wins = plan.windows()
    except ValueError as e:
        return WalkForwardOutcome("UNSUPPORTED", str(e), None, (), "NOT_APPLICABLE_FIXED_CONFIGURATION")
    if not wins:
        return WalkForwardOutcome("UNSUPPORTED", "no complete walk-forward window fits the data range", None, (), "NOT_APPLICABLE_FIXED_CONFIGURATION")  # fmt: skip
    results = []
    for w in wins:
        split = two_way_split(w.train_start, w.train_end, w.test_start, w.test_end)
        cfg = dataclasses.replace(base_config, split=split, evaluation_period=EvaluationPeriod.OUT_OF_SAMPLE)
        try:
            r: ResearchRunResult = harness.run(cfg, strategy, market_data, universe_schedule)
        except ResearchRunFailure as f:  # pragma: no cover - harness returns FAILED results
            results.append({"window": w.to_dict(), "status": "FAILED", "reason": str(f)})
            continue
        results.append({
            "window": w.to_dict(), "run_id": r.run_id, "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "net_return": str(r.metrics["total_return"]) if r.metrics else None,
            "failure": r.failure.to_dict() if r.failure else None,
        })  # fmt: skip
    status = "COMPLETED" if all(x["status"] == "COMPLETED" for x in results) else "FAILED"
    return WalkForwardOutcome(status, None if status == "COMPLETED" else "one or more windows failed", plan.plan_hash(), tuple(results), "NOT_APPLICABLE_FIXED_CONFIGURATION")  # fmt: skip
