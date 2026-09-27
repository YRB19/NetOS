"""Reusable field-validation helpers for domain models.

Private module (leading underscore) — these are implementation details of
`domain/models/`, not part of the public domain-model API. Every domain
model validates its own invariants in `__post_init__`; these helpers exist
so that (a) the same rule is checked the same way everywhere, and (b) each
model's `__post_init__` reads as a list of named checks rather than
duplicated string logic.

All raise `ValueError` on failure — this is a deliberate, uniform choice so
callers can catch one exception type regardless of which field failed.
"""

from __future__ import annotations

from datetime import datetime

from shared.time.clock import ensure_utc


def require_non_empty_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string, got: {value!r}")
    return value


def require_positive(value: object, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive number, got: {value!r}")
    return float(value)


def require_non_negative(value: object, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative number, got: {value!r}")
    return float(value)


def require_unit_interval(value: object, field_name: str) -> float:
    """Require value in the closed interval [0, 1] — used for confidence (SF-10)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number, got: {value!r}")
    if not (0.0 <= float(value) <= 1.0):
        raise ValueError(f"{field_name} must be within [0, 1], got: {value!r}")
    return float(value)


def require_aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime, got: {value!r}")
    return ensure_utc(value)


def require_uuid_like(value: object, field_name: str) -> str:
    """Require a non-empty identifier string.

    We deliberately don't require an RFC-4122 UUID literal — some
    identifiers (e.g. content-addressed StrategyVersion ids) are hex
    digests, not UUIDs — but every identifier field is mandatory and must
    be a non-empty string, which is what this enforces.
    """
    return require_non_empty_str(value, field_name)
