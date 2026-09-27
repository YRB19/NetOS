"""NSE bhavcopy-style CSV adapter. Stage 3 §5, §10 ("one adapter, single
data source is sufficient for Slice 2").

Reconstructed during Slice 3's continuity check (see
docs/implementation-log.md) — the sandbox contained no prior Slice 2
adapter implementation. This is a minimal, functional re-implementation
of the documented adapter contract, sufficient to exercise Slice 3's
feature/context layer; it is not a byte-for-byte restoration of
whatever code may have existed in a prior session.

Produces RAW records only (dicts, not yet validated or normalized) —
per Stage 3 §5, "Raw data (stored as received, before any
transformation — audit/replay value)". Validation and normalization
happen in data/validation and data/normalization respectively; this
adapter must never construct a domain.models.MarketData object itself.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

SOURCE_NAME = "NSE_BHAVCOPY"

# Canonical column names this adapter maps *to* (adapter output shape).
# Any NSE bhavcopy column-naming variant is normalized to these here, at
# the adapter boundary, so nothing downstream needs to know about
# NSE-CSV-specific field names (Stage 3 §19 "the baseline must never
# depend on NSE CSV-specific implementation details").
_COLUMN_ALIASES = {
    "SYMBOL": "symbol",
    "ISIN": "isin",
    "OPEN": "open",
    "OPEN_PRICE": "open",
    "HIGH": "high",
    "HIGH_PRICE": "high",
    "LOW": "low",
    "LOW_PRICE": "low",
    "CLOSE": "close",
    "CLOSE_PRICE": "close",
    "TOTTRDQTY": "volume",
    "TTL_TRD_QNTY": "volume",
    "TIMESTAMP": "date",
    "DATE1": "date",
}


def parse_bhavcopy_csv(csv_text: str, exchange: str = "NSE") -> list[dict]:
    """Parse raw NSE bhavcopy CSV text into a list of raw record dicts.

    Output records are RAW: string values are not yet coerced to
    float/int, dates are not yet parsed to datetimes, and no validation
    has been applied. That is deliberate — validation (data/validation)
    and normalization (data/normalization) are separate pipeline stages.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    records: list[dict] = []
    for row in reader:
        raw: dict = {"exchange": exchange, "source": SOURCE_NAME}
        for key, value in row.items():
            if key is None:
                continue
            canonical_key = _COLUMN_ALIASES.get(key.strip().upper())
            if canonical_key is not None:
                raw[canonical_key] = value.strip() if isinstance(value, str) else value
        records.append(raw)
    return records


def parse_bhavcopy_rows(rows: Iterable[dict], exchange: str = "NSE") -> list[dict]:
    """Same as parse_bhavcopy_csv but for already-parsed dict rows
    (e.g. from an in-memory fixture instead of a CSV file)."""
    records: list[dict] = []
    for row in rows:
        raw: dict = {"exchange": exchange, "source": SOURCE_NAME}
        for key, value in row.items():
            canonical_key = _COLUMN_ALIASES.get(str(key).strip().upper())
            if canonical_key is not None:
                raw[canonical_key] = value
        records.append(raw)
    return records
