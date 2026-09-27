"""Historical data adapter: NSE-bhavcopy-style CSV.

Source selection rationale (full writeup in docs/data-ingestion.md):

  - NSE's daily equity "bhavcopy" is the closest thing to a canonical historical OHLCV source
    for Indian equities, and its column layout (SYMBOL, ISIN, SERIES, DATE, OPEN, HIGH, LOW,
    CLOSE, TOTTRDQTY, ...) is well-documented and stable.
  - This sandbox has no network access (confirmed this session), so a real bhavcopy file could
    not be downloaded from nseindia.com/archives during this build. Downloading and validating
    against a genuine multi-year bhavcopy archive is an explicit, documented follow-up (see
    docs/data-ingestion.md "Known limitations"), not something this adapter fakes.
  - The adapter is built against the bhavcopy *format* (documented in
    data/schemas/nse_bhavcopy_schema.py), and is exercised in this slice's tests against a
    small, deterministic, hand-authored fixture file that matches that format exactly
    (tests/fixtures/historical_data/), clearly labeled as a fixture, not production data.

This module's ONLY job is: read the source file, and produce one RawMarketObservation per row,
with the source's own field names and values completely untouched. It does not validate
numeric sanity, does not normalize units, does not resolve instrument identity beyond what the
source already states, and does not construct MarketData. All of that happens downstream
(data/validation/, data/normalization/), per Stage 3 §5's pipeline ordering.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from domain.models.raw_observation import RawMarketObservation
from shared.time.clock import utc_now


class SourceFormatError(ValueError):
    """Raised when the source file does not match the declared bhavcopy schema at all
    (e.g. missing required columns) — a structural problem, distinct from a single bad row."""


@dataclass(frozen=True)
class RawIngestionResult:
    source_path: str
    observations: tuple[RawMarketObservation, ...]
    raw_source_hash: str  # content hash of the exact file bytes, per shared/versioning


def load_bhavcopy_csv(path: str | Path) -> RawIngestionResult:
    """Read a bhavcopy-format CSV file and produce one RawMarketObservation per data row.

    Every row becomes exactly one RawMarketObservation, with `fields` holding the row's
    original column->value mapping (as strings, exactly as read — no int/float parsing here).
    Header validation happens here (structural — a missing required column is a
    SourceFormatError, since the entire file is then untrustworthy, not just one row).
    Per-row content validation (numeric sanity, OHLC consistency, timestamp parsing) is
    deliberately NOT done here; see data/validation/.
    """
    from data.schemas.nse_bhavcopy_schema import missing_required_columns
    from shared.versioning.content_hash import hash_file

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Historical data source file not found: {p}")

    raw_source_hash = hash_file(p)
    ingestion_time = utc_now()

    with p.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SourceFormatError(f"{p}: file has no header row.")
        missing = missing_required_columns([c for c in reader.fieldnames])
        if missing:
            raise SourceFormatError(
                f"{p}: missing required bhavcopy column(s) {missing}; "
                f"found columns: {list(reader.fieldnames)}"
            )

        observations: list[RawMarketObservation] = []
        for line_number, row in enumerate(reader, start=2):  # header is line 1
            observations.append(
                RawMarketObservation(
                    source="nse_bhavcopy_csv",
                    source_row_ref=f"{p.name}:line {line_number}",
                    fields=dict(row),
                    ingestion_time=ingestion_time,
                )
            )

    return RawIngestionResult(
        source_path=str(p),
        observations=tuple(observations),
        raw_source_hash=raw_source_hash,
    )
