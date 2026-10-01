"""Research-run configuration (Slice 5, spec §6, §7, §12, §22).

`ResearchConfig` is deliberately a plain frozen dataclass with NO validation in
its constructor. Validation lives in `validate_config()` so that an invalid
configuration (e.g. non-positive capital) still yields a reconstructable FAILED
artifact from the runner instead of an exception that loses the research
context (spec §24). Identity (`experiment_id`, `run_id`) is derived from the
meaningful inputs only — never from wall-clock time, hostnames or paths (§7).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from data.features.feature_sets import TIER1_CONTEXT_FEATURE_SET_ID
from domain.models.research_artifacts import SplitSpec
from shared.costs.models import TradeType
from shared.versioning.content_hash import hash_json_stable

HARNESS_VERSION = "research-harness-v1"
SUPPORTED_EXECUTION_ASSUMPTIONS = ("NEXT_BAR_OPEN",)
SUPPORTED_CURRENCY = "INR"


class EvaluationPeriod(str, Enum):  # noqa: UP042
    """Which declared SplitSpec window this run replays."""

    IN_SAMPLE = "IN_SAMPLE"  # SplitSpec train window
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"  # SplitSpec test window


class OrderRejectionPolicy(str, Enum):  # noqa: UP042
    """What happens when a simulated order cannot be executed (cash / no price).

    FAIL_RUN (default) fails closed: the run is marked FAILED and never reported as
    a clean result. REJECT_AND_CONTINUE records a rejection artifact and continues;
    rejections are counted in the metrics either way.
    """

    FAIL_RUN = "FAIL_RUN"
    REJECT_AND_CONTINUE = "REJECT_AND_CONTINUE"


@dataclass(frozen=True)
class ResearchConfig:
    hypothesis: str
    pre_registered_criteria: str
    initial_capital: Decimal | int | str  # explicit, never defaulted (spec §12); INR, <= 2 dp
    cost_schedule_version: str  # explicit, never defaulted to "latest" (spec §15)
    split: SplitSpec
    evaluation_period: EvaluationPeriod
    currency: str = SUPPORTED_CURRENCY
    trade_type: TradeType = TradeType.DELIVERY
    execution_assumption: str = "NEXT_BAR_OPEN"
    allocation_cash_buffer: Decimal | int | str = "0.01"
    max_staleness_days: int = 0
    carry_forward_marks: bool = False
    order_rejection_policy: OrderRejectionPolicy = OrderRejectionPolicy.FAIL_RUN
    strategy_configured_through: datetime | None = None
    acknowledge_future_cost_schedule: bool = False
    feature_set_id: str = TIER1_CONTEXT_FEATURE_SET_ID


# ---------------------------------------------------------------------------
# Tolerant canonicalisation (must never raise: used for failure identity too)
# ---------------------------------------------------------------------------


def _canon(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return f"decimal:{value}"
        return format(value.normalize(), "f")
    if isinstance(value, float):
        return f"float:{value!r}"
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return f"NAIVE:{value.isoformat()}"
        return value.astimezone(__import__("datetime").timezone.utc).isoformat()
    if isinstance(value, SplitSpec):
        return {
            "train_start": _canon(value.train_start),
            "train_end": _canon(value.train_end),
            "validation_start": _canon(value.validation_start),
            "validation_end": _canon(value.validation_end),
            "test_start": _canon(value.test_start),
            "test_end": _canon(value.test_end),
        }
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return f"{type(value).__name__}:{value!r}"


def config_payload(config: ResearchConfig) -> dict:
    """The canonical, JSON-safe, order-independent view of a configuration."""
    return {
        "hypothesis": _canon(config.hypothesis),
        "pre_registered_criteria": _canon(config.pre_registered_criteria),
        "initial_capital": _canon(config.initial_capital),
        "currency": _canon(config.currency),
        "cost_schedule_version": _canon(config.cost_schedule_version),
        "split": _canon(config.split),
        "evaluation_period": _canon(config.evaluation_period),
        "trade_type": _canon(config.trade_type),
        "execution_assumption": _canon(config.execution_assumption),
        "allocation_cash_buffer": _canon(config.allocation_cash_buffer),
        "max_staleness_days": _canon(config.max_staleness_days),
        "carry_forward_marks": _canon(config.carry_forward_marks),
        "order_rejection_policy": _canon(config.order_rejection_policy),
        "strategy_configured_through": _canon(config.strategy_configured_through),
        "acknowledge_future_cost_schedule": _canon(config.acknowledge_future_cost_schedule),
        "feature_set_id": _canon(config.feature_set_id),
    }


def experiment_payload(
    config: ResearchConfig,
    *,
    strategy_version_id: str,
    baseline_strategy_version_ids: tuple[str, ...],
    data_snapshot_version: str,
    universe_schedule: list[tuple[str, str]],
) -> dict:
    """Everything that defines WHAT is being evaluated (spec §7)."""
    return {
        "config": config_payload(config),
        "strategy_version_id": _canon(strategy_version_id),
        "baseline_strategy_version_ids": [_canon(b) for b in baseline_strategy_version_ids],
        "data_snapshot_version": _canon(data_snapshot_version),
        "universe_schedule": [[_canon(v), _canon(e)] for v, e in universe_schedule],
    }


def experiment_id_for(payload: dict) -> str:
    return "exp_" + hash_json_stable(payload)[:32]


def run_id_for(experiment_id: str, harness_version: str = HARNESS_VERSION) -> str:
    """A run is one execution of an experiment by a given harness version."""
    return "run_" + hash_json_stable({"experiment_id": experiment_id, "harness": harness_version})[:32]


_COMPARISON_CONFIG_KEYS = (
    "initial_capital",
    "currency",
    "cost_schedule_version",
    "split",
    "evaluation_period",
    "trade_type",
    "execution_assumption",
    "allocation_cash_buffer",
    "max_staleness_days",
    "carry_forward_marks",
    "order_rejection_policy",
    "feature_set_id",
    "acknowledge_future_cost_schedule",
)


def comparison_fingerprint(payload: dict) -> str:
    """Identity of everything that must be identical for an apples-to-apples comparison
    (spec §19/§21): data, universe, window, capital, cost schedule, execution assumptions.

    Deliberately EXCLUDES the strategy, hypothesis text and pre-registered-criteria text.
    """
    shared = {
        "config": {k: payload["config"][k] for k in _COMPARISON_CONFIG_KEYS},
        "data_snapshot_version": payload["data_snapshot_version"],
        "universe_schedule": payload["universe_schedule"],
    }
    return hash_json_stable(shared)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def parse_money(value: object, name: str, errors: list[str]) -> Decimal | None:
    if isinstance(value, bool) or isinstance(value, float):
        errors.append(
            f"{name} must be a Decimal, int or numeric string (binary floats are rejected "
            f"for money), got {type(value).__name__}"
        )
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(value)  # type: ignore[arg-type]
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{name} is not a valid decimal amount: {value!r}")
        return None
    if not d.is_finite():
        errors.append(f"{name} must be finite, got {value!r}")
        return None
    return d


def resolved_capital(config: ResearchConfig) -> Decimal:
    errors: list[str] = []
    d = parse_money(config.initial_capital, "initial_capital", errors)
    if d is None:
        raise ValueError("; ".join(errors))
    return d


def resolved_buffer(config: ResearchConfig) -> Decimal:
    errors: list[str] = []
    d = parse_money(config.allocation_cash_buffer, "allocation_cash_buffer", errors)
    if d is None:
        raise ValueError("; ".join(errors))
    return d


def validate_config(config: ResearchConfig, known_schedule_versions: set[str]) -> list[str]:
    """Return every configuration problem found (empty list == valid)."""
    errors: list[str] = []

    for name in ("hypothesis", "pre_registered_criteria"):
        v = getattr(config, name)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"{name} must be a non-empty string (ER-8 pre-registration)")

    cap = parse_money(config.initial_capital, "initial_capital", errors)
    if cap is not None:
        if cap <= 0:
            errors.append(f"initial_capital must be positive, got {cap}")
        elif cap != cap.quantize(Decimal("0.01")):
            errors.append(f"initial_capital must have at most 2 decimal places (INR), got {cap}")

    if config.currency != SUPPORTED_CURRENCY:
        errors.append(f"currency must be {SUPPORTED_CURRENCY!r}, got {config.currency!r}")

    if not isinstance(config.cost_schedule_version, str) or not config.cost_schedule_version:
        errors.append("cost_schedule_version must be an explicit non-empty string")
    elif config.cost_schedule_version not in known_schedule_versions:
        errors.append(
            f"unknown cost schedule version {config.cost_schedule_version!r}; "
            f"known: {sorted(known_schedule_versions)}"
        )

    if not isinstance(config.split, SplitSpec):
        errors.append("split must be a SplitSpec (ER-2: a declared split is mandatory)")
    if not isinstance(config.evaluation_period, EvaluationPeriod):
        errors.append("evaluation_period must be an EvaluationPeriod")
    if config.trade_type is not TradeType.DELIVERY:
        errors.append(
            "only TradeType.DELIVERY is supported in Slice 5 (intraday square-off is not modeled)"
        )
    if config.execution_assumption not in SUPPORTED_EXECUTION_ASSUMPTIONS:
        errors.append(
            f"unsupported execution_assumption {config.execution_assumption!r}; "
            f"supported: {SUPPORTED_EXECUTION_ASSUMPTIONS}"
        )

    buf = parse_money(config.allocation_cash_buffer, "allocation_cash_buffer", errors)
    if buf is not None and not (Decimal(0) <= buf < Decimal(1)):
        errors.append(f"allocation_cash_buffer must be in [0, 1), got {buf}")

    if (
        isinstance(config.max_staleness_days, bool)
        or not isinstance(config.max_staleness_days, int)
        or config.max_staleness_days < 0
    ):
        errors.append("max_staleness_days must be a non-negative int")
    if not isinstance(config.carry_forward_marks, bool):
        errors.append("carry_forward_marks must be a bool")
    if not isinstance(config.order_rejection_policy, OrderRejectionPolicy):
        errors.append("order_rejection_policy must be an OrderRejectionPolicy")
    if config.strategy_configured_through is not None and (
        not isinstance(config.strategy_configured_through, datetime)
        or config.strategy_configured_through.tzinfo is None
    ):
        errors.append("strategy_configured_through must be a timezone-aware datetime or None")
    if not isinstance(config.acknowledge_future_cost_schedule, bool):
        errors.append("acknowledge_future_cost_schedule must be a bool")
    if not isinstance(config.feature_set_id, str) or not config.feature_set_id:
        errors.append("feature_set_id must be a non-empty string")

    if cap is not None and isinstance(cap, Decimal) and math.isnan(float(cap)):
        errors.append("initial_capital must not be NaN")
    return errors


def window_bounds(config: ResearchConfig) -> tuple[datetime, datetime]:
    """(start, end) inclusive decision-timestamp window for this run."""
    s = config.split
    if config.evaluation_period is EvaluationPeriod.IN_SAMPLE:
        return s.train_start, s.train_end
    return s.test_start, s.test_end


def two_way_split(
    train_start: datetime, train_end: datetime, test_start: datetime, test_end: datetime
) -> SplitSpec:
    """Build a SplitSpec with no validation window (encoded as validation == [train_end, train_end])."""
    return SplitSpec(
        train_start=train_start,
        train_end=train_end,
        validation_start=train_end,
        validation_end=train_end,
        test_start=test_start,
        test_end=test_end,
    )


def validation_window_is_empty(split: SplitSpec) -> bool:
    return split.validation_start == split.validation_end == split.train_end
