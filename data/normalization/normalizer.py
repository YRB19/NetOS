"""Normalization: raw records -> canonical MarketData. Stage 3 §5.

Reconstructed during Slice 3's continuity check; see
docs/implementation-log.md.

Corporate-action handling (splits/bonuses/dividends) is explicitly OUT
OF SCOPE for this minimal reconstruction (DR-2 is a `Should` in Stage 1
and not required to exercise Slice 3) — this is a known, documented
limitation, not a silent omission. See docs/slice-status.md.
"""

from __future__ import annotations

from datetime import date, datetime

from data.validation.validators import validate_raw_record
from domain.models.instrument import Instrument
from domain.models.market_data import MarketData
from shared.time.clock import UTC
from shared.versioning.versioning import make_version_id


class AlternateNormalizationResult:
    """Outcome of normalizing a batch of raw records. Both accepted
    MarketData and rejected raw records (with reasons) are kept — SF-1
    gaps must be auditable, not silently dropped (Slice 3 spec §7 / §5)."""

    def __init__(self) -> None:
        self.accepted: list[MarketData] = []
        self.instruments: dict[str, Instrument] = {}
        self.rejected: list[tuple[dict, list[str]]] = []


def _parse_observation_datetime(raw_date: str) -> datetime:
    """NSE bhavcopy dates are calendar dates with no intraday time; we
    represent the observation as end-of-trading-day UTC (15:30 IST close
    == 10:00 UTC) so every MarketData timestamp is unambiguous and
    comparable. Accepts DD-MMM-YYYY or YYYY-MM-DD."""
    raw_date = raw_date.strip()
    parsed_date: date
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d%m%Y"):
        try:
            parsed_date = datetime.strptime(raw_date, fmt).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Unrecognized date format: {raw_date!r}")
    # NSE cash-market close is 15:30 IST = 10:00 UTC.
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, 10, 0, 0, tzinfo=UTC)


def normalize_records(raw_records: list[dict], ingestion_time: datetime) -> AlternateNormalizationResult:
    """Validate and normalize a batch of raw adapter records into
    canonical MarketData, per the Stage 3 §5 pipeline:
    validation -> normalization -> canonical MarketData.
    """
    if ingestion_time.tzinfo is None:
        raise ValueError("ingestion_time must be timezone-aware UTC")

    result = AlternateNormalizationResult()
    for raw in raw_records:
        errors = validate_raw_record(raw)
        if errors:
            result.rejected.append((raw, errors))
            continue
        try:
            observation_ts = _parse_observation_datetime(str(raw["date"]))
            instrument = Instrument(
                isin=str(raw["isin"]),
                symbol=str(raw["symbol"]),
                exchange=str(raw["exchange"]),
            )
            market_data = MarketData(
                instrument_id=instrument.instrument_id,
                timestamp=observation_ts,
                open=float(raw["open"]),
                high=float(raw["high"]),
                low=float(raw["low"]),
                close=float(raw["close"]),
                volume=int(float(raw["volume"])),
                source=str(raw["source"]),
                data_snapshot_version=make_version_id("slice3_normalizer_v1", raw_records),
                ingestion_time=ingestion_time,
            )
        except (ValueError, KeyError) as exc:
            result.rejected.append((raw, [str(exc)]))
            continue

        result.accepted.append(market_data)
        result.instruments[instrument.instrument_id] = instrument

    return result
