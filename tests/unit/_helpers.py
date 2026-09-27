"""Small, dependency-free helpers shared by the unit test suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc(offset_days: float = 0.0) -> datetime:
    """A fixed, deterministic-enough UTC timestamp for test construction."""
    base = datetime(2026, 1, 15, 9, 15, 0, tzinfo=UTC)
    return base + timedelta(days=offset_days)


NAIVE_DATETIME = datetime(2026, 1, 15, 9, 15, 0)  # deliberately no tzinfo, for negative tests
