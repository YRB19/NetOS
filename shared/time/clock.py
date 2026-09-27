"""Shared time utilities.

Stage 3 §5 requires: "all timestamps converted to and stored as UTC; display/decision-window
logic uses IST via a single shared time utility (shared/time/), never ad hoc per-module
conversion."

This module is the single source of truth for:
  - parsing a source timestamp into a UTC-aware datetime
  - converting a UTC-aware datetime to IST for display
  - evaluating whether a timestamp is "fresh" as of a reference instant

No other module in this repository should perform its own timezone arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

# India Standard Time is a fixed UTC+5:30 offset with no daylight-saving rules.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
UTC = UTC


class TimestampError(ValueError):
    """Raised when a timestamp cannot be safely interpreted."""


def parse_source_timestamp(
    value: datetime, *, assumed_source_tz: timezone | None = None
) -> datetime:
    """Normalize a source-provided timestamp into a UTC-aware datetime.

    Per Stage 3 §5: "Do not assume naive timestamps are UTC. If the source format contains a
    timezone assumption, document it explicitly." Callers (adapters) MUST declare the source's
    timezone assumption explicitly via `assumed_source_tz`; this function refuses to silently
    guess.

    Args:
        value: the timestamp as parsed from the source, may be naive or aware.
        assumed_source_tz: required if `value` is naive — the timezone the adapter has
            documented for this source. If `value` is already timezone-aware, this argument
            is ignored (the embedded tzinfo is authoritative).

    Raises:
        TimestampError: if `value` is naive and no `assumed_source_tz` was supplied.
    """
    if value.tzinfo is None:
        if assumed_source_tz is None:
            raise TimestampError(
                "Naive timestamp received with no declared source timezone. "
                "Adapters must explicitly state the source's timezone assumption "
                "(see docs/data-ingestion.md) rather than have this utility guess."
            )
        value = value.replace(tzinfo=assumed_source_tz)
    return value.astimezone(UTC)


def to_ist(value: datetime) -> datetime:
    """Convert a timezone-aware datetime to IST for display/decision-window logic."""
    if value.tzinfo is None:
        raise TimestampError("to_ist() requires a timezone-aware datetime; got a naive one.")
    return value.astimezone(IST)


def utc_now() -> datetime:
    """The single source of truth for 'now', always UTC-aware.

    Deliberately isolated here so ingestion/normalization code never calls datetime.now()
    or datetime.utcnow() directly (the latter returns a naive datetime, a documented footgun).
    """
    return datetime.now(UTC)


@dataclass(frozen=True)
class FreshnessResult:
    is_fresh: bool
    age_seconds: float
    threshold_seconds: float
    observation_time: datetime
    reference_time: datetime


def evaluate_freshness(
    observation_time: datetime,
    *,
    threshold_seconds: float,
    reference_time: datetime | None = None,
) -> FreshnessResult:
    """Evaluate whether `observation_time` is fresh relative to `reference_time`.

    Per Stage 3 §5 (SF-2): staleness detection must be a real, evaluable check, not an
    assumption. This function is deliberately generic — the live pipeline (a future slice)
    will use it against wall-clock "now"; historical ingestion (this slice) uses it only to
    prove the mechanism works (a historical record is intentionally "stale" relative to the
    present, which is expected and not an error for ingestion purposes).

    Both `observation_time` and `reference_time` must be timezone-aware; this function does
    not guess a timezone for either.
    """
    if observation_time.tzinfo is None:
        raise TimestampError("evaluate_freshness() requires a timezone-aware observation_time.")
    ref = reference_time if reference_time is not None else utc_now()
    if ref.tzinfo is None:
        raise TimestampError("evaluate_freshness() requires a timezone-aware reference_time.")
    if threshold_seconds < 0:
        raise TimestampError("threshold_seconds must be non-negative.")

    age = (ref - observation_time).total_seconds()
    # A negative age means the observation claims to be from the future relative to the
    # reference instant. That is never treated as "fresh" — it is an anomaly, not a pass —
    # per the fail-closed principle (Stage 2 Principle 7): "cannot verify as sane" is not
    # the same as "verified and current."
    is_fresh = 0 <= age <= threshold_seconds
    return FreshnessResult(
        is_fresh=is_fresh,
        age_seconds=age,
        threshold_seconds=threshold_seconds,
        observation_time=observation_time,
        reference_time=ref,
    )


def ensure_utc(value: datetime) -> datetime:
    return parse_source_timestamp(value)


to_utc = ensure_utc


def is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)
