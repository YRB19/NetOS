"""Validation and staleness checks. Stage 3 §5 (SF-1, SF-2).

Reconstructed during Slice 3's continuity check; see
docs/implementation-log.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from shared.time.clock import evaluate_freshness

REQUIRED_RAW_FIELDS = (
    "isin",
    "symbol",
    "exchange",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
)


def validate_raw_record(record: dict) -> list[str]:
    """Return a list of validation error strings; empty list means valid.

    This is a plausibility/completeness check on a RAW record (still
    string-typed in places), per Stage 3 §5's "Validation (schema check,
    plausibility bounds e.g. price > 0, volume >= 0)" stage — it runs
    BEFORE normalization, so it must not assume values are already
    numeric.
    """
    errors: list[str] = []
    for field_name in REQUIRED_RAW_FIELDS:
        if field_name not in record or record[field_name] in (None, ""):
            errors.append(f"missing required field: {field_name}")
    if errors:
        # Can't safely do numeric/range checks on a record missing fields.
        return errors

    try:
        o, h, low, c = (
            float(record["open"]),
            float(record["high"]),
            float(record["low"]),
            float(record["close"]),
        )
    except (TypeError, ValueError):
        errors.append("open/high/low/close must be numeric")
        return errors

    try:
        v = float(record["volume"])
    except (TypeError, ValueError):
        errors.append("volume must be numeric")
        return errors

    if o <= 0 or h <= 0 or low <= 0 or c <= 0:
        errors.append("open/high/low/close must all be > 0")
    if v < 0:
        errors.append("volume must be >= 0")
    if low > h:
        errors.append("low cannot exceed high")
    if not errors and not (low <= o <= h):
        errors.append("open must lie within [low, high]")
    if not errors and not (low <= c <= h):
        errors.append("close must lie within [low, high]")

    return errors


def is_stale(observation_time: datetime, as_of: datetime, max_age: timedelta) -> bool:
    """SF-2: staleness check. observation_time and as_of must both be
    timezone-aware (raises otherwise, to avoid a silent naive-time bug
    masking a real staleness condition)."""
    if observation_time.tzinfo is None or as_of.tzinfo is None:
        raise ValueError("is_stale() requires timezone-aware datetimes")
    return not evaluate_freshness(
        observation_time, reference_time=as_of, threshold_seconds=max_age.total_seconds()
    ).is_fresh
