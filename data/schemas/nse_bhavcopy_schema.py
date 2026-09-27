"""Documented raw-input schema for the NSE-bhavcopy-style historical CSV source.

This is NOT a duplicate of the canonical domain model (domain/models/market_data.py). It
describes what a specific *source format* is expected to look like at the raw-ingestion
boundary, so validation can check "did the source give us what we expect" before any field
gets renamed or reinterpreted. See docs/data-ingestion.md for the full source-format writeup,
including why this specific format was chosen and its known limitations.

Column semantics (matching NSE's historical equity bhavcopy convention):
    SYMBOL      - trading symbol, e.g. "RELIANCE"
    ISIN        - canonical instrument identifier
    SERIES      - "EQ" for the equity series; other series values are out of scope (TR-1)
    DATE        - trading date, format DD-MON-YYYY, e.g. "02-JAN-2024"
    OPEN/HIGH/LOW/CLOSE - as-traded (unadjusted) prices in INR
    LAST        - last traded price (not used by this pipeline; retained in the raw record)
    PREVCLOSE   - previous close (not used by this pipeline; retained in the raw record)
    TOTTRDQTY   - total traded quantity (volume)

Dates in this source are calendar dates with no intraday time component. This pipeline's
documented, explicit assumption (see docs/data-ingestion.md) is that a bhavcopy date
represents that trading day's session close, which NSE fixes at 15:30 IST. That assumption is
applied once, in the adapter, and is never re-derived elsewhere.
"""

from __future__ import annotations

REQUIRED_COLUMNS: tuple[str, ...] = (
    "SYMBOL",
    "ISIN",
    "SERIES",
    "DATE",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "TOTTRDQTY",
)

# Columns retained in the raw record for auditability but not consumed by normalization.
OPTIONAL_COLUMNS: tuple[str, ...] = ("LAST", "PREVCLOSE")

DATE_FORMAT = "%d-%b-%Y"  # e.g. "02-JAN-2024"

# NSE's fixed regular-market close time, used only to give a bhavcopy's date-only timestamp a
# concrete, documented time-of-day before conversion to UTC (see shared/time/clock.py).
SESSION_CLOSE_HOUR_IST = 15
SESSION_CLOSE_MINUTE_IST = 30

ALLOWED_SERIES: frozenset[str] = frozenset({"EQ"})


def missing_required_columns(header: list[str]) -> list[str]:
    present = {c.strip().upper() for c in header}
    return [c for c in REQUIRED_COLUMNS if c not in present]
