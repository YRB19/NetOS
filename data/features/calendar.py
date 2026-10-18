"""Calendar-month arithmetic used by the Tier-2 momentum feature builder (Slice 6).

Pure functions, UTC-aware datetimes in, UTC-aware datetimes out. No wall clock.
"""

from __future__ import annotations

import calendar
from datetime import datetime


def shift_months(ts: datetime, months: int) -> datetime:
    """Return `ts` moved by a whole number of calendar months (day clamped to month end)."""
    total = ts.year * 12 + (ts.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(ts.day, calendar.monthrange(year, month)[1])
    return ts.replace(year=year, month=month, day=day)


def end_of_day(ts: datetime) -> datetime:
    """Last representable instant of `ts`'s calendar day (same tzinfo)."""
    return ts.replace(hour=23, minute=59, second=59, microsecond=999999)


def month_key(ts: datetime) -> tuple[int, int]:
    return (ts.year, ts.month)
