"""Basic contamination guards (Slice 5, spec §9, §22, §23).

Every guard FAILS CLOSED: a violation raises `ResearchRunFailure(CONTAMINATION)`;
the run is never allowed to continue and be reported as successful.

Static (pre-replay) checks
  * split windows strictly separated (train < validation < test; no shared instants)
  * OOS evaluation: strategy configured no later than the end of the training window
  * cost schedule not silently from the future of the evaluation window

Per-cycle checks
  * every observation handed to feature building has timestamp <= decision time
  * every FeatureSnapshot is stamped with the decision time and cites only
    observations at/before it
  * the universe in force has effective_from <= decision time
  * no observation beyond the evaluation window end is ever consumed

These are *basic* guards. They do not replace PBO/CSCV (ER-4), which is a later slice.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from data.features.universe import PermittedUniverse
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.market_data import MarketData
from domain.models.research_artifacts import ContaminationCheckResult, SplitSpec
from research.harness.failures import FailureCategory, ResearchRunFailure


def _fail(detail: str, **ctx: object) -> ResearchRunFailure:
    return ResearchRunFailure(FailureCategory.CONTAMINATION, detail, **ctx)


def _validation_is_empty(split: SplitSpec) -> bool:
    return split.validation_start == split.validation_end == split.train_end


def check_split_separation(split: SplitSpec) -> None:
    """Strict separation: a shared instant between windows counts as overlap."""
    if not _validation_is_empty(split):
        if not split.train_end < split.validation_start:
            raise _fail(
                f"train window end {split.train_end.isoformat()} is not strictly before "
                f"validation start {split.validation_start.isoformat()} (overlap)"
            )
        if not split.validation_end < split.test_start:
            raise _fail(
                f"validation window end {split.validation_end.isoformat()} is not strictly "
                f"before test start {split.test_start.isoformat()} (overlap)"
            )
    elif not split.train_end < split.test_start:
        raise _fail(
            f"train window end {split.train_end.isoformat()} is not strictly before test start "
            f"{split.test_start.isoformat()} (train/test overlap)"
        )


def check_strategy_configuration_cutoff(
    split: SplitSpec, evaluation_is_out_of_sample: bool, configured_through: datetime | None
) -> dict:
    """An out-of-sample claim is void if the strategy was configured on/after test start.

    Returns a small dict recorded in the contamination report. `configured_through=None`
    is accepted (e.g. a zero-parameter baseline) but is RECORDED as undeclared so that
    the claim is visible, not silently assumed.
    """
    declared = configured_through is not None
    if evaluation_is_out_of_sample and declared and configured_through >= split.test_start:  # type: ignore[operator]
        raise _fail(
            f"strategy configuration used data through {configured_through.isoformat()}, which "
            f"is not before the out-of-sample test start {split.test_start.isoformat()}"
        )
    if not evaluation_is_out_of_sample and declared and configured_through > split.train_end:  # type: ignore[operator]
        raise _fail(
            f"in-sample evaluation but strategy was configured through "
            f"{configured_through.isoformat()}, after train end {split.train_end.isoformat()}"
        )
    return {"strategy_configuration_declared": declared}


def check_cost_schedule_not_from_future(
    schedule_effective_date: str | None,
    window_start: datetime,
    acknowledged: bool,
    schedule_version: str,
) -> dict:
    """A schedule effective AFTER the window start may only be used when the experiment
    explicitly acknowledges it models a known-future configuration (spec §9)."""
    if schedule_effective_date is None:
        return {"cost_schedule_effective_date": None, "future_cost_schedule_acknowledged": False}
    effective = date.fromisoformat(schedule_effective_date)
    is_future = effective > window_start.date()
    if is_future and not acknowledged:
        raise _fail(
            f"cost schedule {schedule_version!r} is effective {schedule_effective_date}, after "
            f"the evaluation window start {window_start.date().isoformat()}; set "
            f"acknowledge_future_cost_schedule=True to model a known-future configuration explicitly"
        )
    return {
        "cost_schedule_effective_date": schedule_effective_date,
        "future_cost_schedule_acknowledged": bool(is_future and acknowledged),
    }


def check_observations_not_from_future(
    observations: Sequence[MarketData], decision_ts: datetime, window_end: datetime
) -> None:
    for r in observations:
        if r.timestamp > decision_ts:
            raise _fail(
                f"observation for {r.instrument_id} at {r.timestamp.isoformat()} is after "
                f"decision time {decision_ts.isoformat()} (lookahead)",
                instrument_id=r.instrument_id,
            )
        if r.timestamp > window_end:
            raise _fail(
                f"observation for {r.instrument_id} at {r.timestamp.isoformat()} is after the "
                f"evaluation cutoff {window_end.isoformat()}"
            )


def check_snapshots_not_from_future(
    snapshots: Sequence[FeatureSnapshot], decision_ts: datetime
) -> None:
    for s in snapshots:
        if s.decision_timestamp != decision_ts:
            raise _fail(
                f"snapshot for {s.instrument_id} is stamped {s.decision_timestamp.isoformat()}, "
                f"expected decision time {decision_ts.isoformat()}"
            )
        for ref in s.source_refs:
            if ref.timestamp > decision_ts:
                raise _fail(
                    f"snapshot for {s.instrument_id} cites source observation at "
                    f"{ref.timestamp.isoformat()}, after decision time {decision_ts.isoformat()}"
                )


def check_universe_not_from_future(universe: PermittedUniverse, decision_ts: datetime) -> None:
    if universe.effective_from > decision_ts:
        raise _fail(
            f"universe {universe.version} is effective from {universe.effective_from.isoformat()}, "
            f"after decision time {decision_ts.isoformat()} (future universe membership)"
        )


def passed_result(detail: str, **ctx: object) -> ContaminationCheckResult:
    text = detail + (" | " + "; ".join(f"{k}={v}" for k, v in sorted(ctx.items())) if ctx else "")
    return ContaminationCheckResult(passed=True, detail=text, overlap_detected=False)


def failed_result(detail: str) -> ContaminationCheckResult:
    return ContaminationCheckResult(passed=False, detail=detail, overlap_detected=True)
