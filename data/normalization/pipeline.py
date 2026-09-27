"""Normalization pipeline: RawMarketObservation (bhavcopy-format) -> canonical MarketData.

Implements the Stage 3 §5 flow for this slice's one supported source:

    Raw Records -> Validation -> Normalization -> Corporate Action Handling -> Canonical
    MarketData

Determinism guarantee (Stage 3 §5 / §19): the same raw observations, run through the same
NORMALIZATION_CODE_VERSION, always produce the same accepted/rejected sets and the same
data_snapshot_version. No wall-clock reads, no network calls, no randomness occur inside this
module (the only "current time" used anywhere in the historical pipeline is the adapter's
ingestion_time stamp, captured once at read time and carried through immutably — never
re-read here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from data.normalization.corporate_actions import (
    AdjustedCandidate,
    SplitAction,
    apply_split_adjustment,
)
from data.schemas.nse_bhavcopy_schema import (
    DATE_FORMAT,
    SESSION_CLOSE_HOUR_IST,
    SESSION_CLOSE_MINUTE_IST,
)
from data.validation.market_data_validation import CandidateOHLCV, validate_ohlcv
from data.validation.raw_validation import validate_raw_bhavcopy_observation
from domain.models.instrument import Instrument
from domain.models.market_data import MarketData
from domain.models.raw_observation import RawMarketObservation
from shared.time.clock import IST, TimestampError, parse_source_timestamp
from shared.versioning.content_hash import data_snapshot_version

# Bumped whenever the transformation logic in this module changes in a way that could alter
# output for the same raw input. This is the "normalization code version" half of the data
# snapshot version identifier (Stage 3 §5/§19).
NORMALIZATION_CODE_VERSION = "nse_bhavcopy_normalizer_v1"

# Bhavcopy carries no lot-size field; NSE equity (cash segment) lot size is 1 share.
_EQUITY_LOT_SIZE = 1
_ADAPTER_EXCHANGE = "NSE"  # this adapter is scoped to NSE bhavcopy specifically


@dataclass(frozen=True)
class RejectedRecord:
    raw_id: str
    source_row_ref: str
    reason_code: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class NormalizationResult:
    data_snapshot_version: str
    accepted: tuple[MarketData, ...]
    rejected: tuple[RejectedRecord, ...]
    instruments: tuple[Instrument, ...]  # distinct instruments observed among accepted records


def _parse_bhavcopy_date(raw_date: str, source_row_ref: str) -> datetime:
    """Parse a bhavcopy DATE field into a UTC-aware datetime.

    Documented, explicit assumption (data/schemas/nse_bhavcopy_schema.py): a bhavcopy date has
    no intraday time component, so this pipeline assigns it NSE's fixed 15:30 IST session-close
    time before converting to UTC. This assumption is applied exactly once, here, and nowhere
    else in the codebase re-derives or re-guesses it.
    """
    naive = datetime.strptime(raw_date.strip(), DATE_FORMAT)
    naive_ist_session_close = naive.replace(
        hour=SESSION_CLOSE_HOUR_IST, minute=SESSION_CLOSE_MINUTE_IST, second=0, microsecond=0
    )
    return parse_source_timestamp(naive_ist_session_close, assumed_source_tz=IST)


def normalize_bhavcopy_batch(
    raw_observations: tuple[RawMarketObservation, ...],
    *,
    raw_source_hash: str,
    splits: tuple[SplitAction, ...] = (),
) -> NormalizationResult:
    """Normalize a batch of bhavcopy-format RawMarketObservations into canonical MarketData.

    Duplicate-handling policy (documented decision, see docs/data-ingestion.md
    "Duplicate observations"):
      - Two accepted records sharing the canonical identity (instrument_id, timestamp, source)
        with IDENTICAL OHLCV values are treated as an exact duplicate: the first is kept, the
        second is rejected with reason_code=DUPLICATE_EXACT.
      - Two accepted records sharing that identity with DIFFERENT OHLCV values are treated as a
        source revision/correction: BOTH are retained as separate MarketData records (this
        pipeline never edits or discards a prior canonical record in place, per Stage 3 §5's
        "corrections are new records" rule). This is intentional, not a bug — the later record
        does not supersede the earlier one at the storage layer; a consumer choosing "most
        recent belief" is a downstream policy, not this pipeline's job.
    """
    snapshot_version = data_snapshot_version(raw_source_hash, NORMALIZATION_CODE_VERSION)

    accepted: list[MarketData] = []
    rejected: list[RejectedRecord] = []
    instruments: dict[str, Instrument] = {}
    seen_identity_values: dict[tuple, tuple[float, float, float, float, int]] = {}

    for obs in raw_observations:
        raw_check = validate_raw_bhavcopy_observation(obs)
        if not raw_check.ok:
            rejected.append(
                RejectedRecord(
                    raw_id=obs.raw_id,
                    source_row_ref=obs.source_row_ref,
                    reason_code="RAW_VALIDATION_FAILED",
                    reasons=raw_check.reasons,
                )
            )
            continue

        fields = obs.fields
        isin = str(fields["ISIN"]).strip()
        symbol = str(fields["SYMBOL"]).strip()

        try:
            timestamp = _parse_bhavcopy_date(str(fields["DATE"]), obs.source_row_ref)
        except (TimestampError, ValueError) as exc:
            rejected.append(
                RejectedRecord(
                    raw_id=obs.raw_id,
                    source_row_ref=obs.source_row_ref,
                    reason_code="TIMESTAMP_ERROR",
                    reasons=(str(exc),),
                )
            )
            continue

        try:
            candidate = CandidateOHLCV(
                open=float(fields["OPEN"]),
                high=float(fields["HIGH"]),
                low=float(fields["LOW"]),
                close=float(fields["CLOSE"]),
                volume=int(float(fields["TOTTRDQTY"])),
            )
        except (TypeError, ValueError) as exc:
            rejected.append(
                RejectedRecord(
                    raw_id=obs.raw_id,
                    source_row_ref=obs.source_row_ref,
                    reason_code="NUMERIC_PARSE_ERROR",
                    reasons=(str(exc),),
                )
            )
            continue

        numeric_check = validate_ohlcv(candidate)
        if not numeric_check.ok:
            rejected.append(
                RejectedRecord(
                    raw_id=obs.raw_id,
                    source_row_ref=obs.source_row_ref,
                    reason_code="NUMERIC_VALIDATION_FAILED",
                    reasons=numeric_check.reasons,
                )
            )
            continue

        adjustment: AdjustedCandidate = apply_split_adjustment(isin, timestamp, candidate, splits)
        final = adjustment.ohlcv

        identity_key = (isin, timestamp, "nse_bhavcopy_csv")
        value_signature = (final.open, final.high, final.low, final.close, final.volume)
        prior_signature = seen_identity_values.get(identity_key)
        if prior_signature == value_signature:
            rejected.append(
                RejectedRecord(
                    raw_id=obs.raw_id,
                    source_row_ref=obs.source_row_ref,
                    reason_code="DUPLICATE_EXACT",
                    reasons=(f"identical record already accepted for identity {identity_key}",),
                )
            )
            continue
        seen_identity_values[identity_key] = value_signature

        try:
            market_data = MarketData(
                instrument_id=isin,
                timestamp=timestamp,
                open=final.open,
                high=final.high,
                low=final.low,
                close=final.close,
                volume=final.volume,
                source="nse_bhavcopy_csv",
                ingestion_time=obs.ingestion_time,
                data_snapshot_version=snapshot_version,
                adjusted=adjustment.adjusted,
                raw_ref=obs.raw_id,
            )
        except ValueError as exc:
            # Defense-in-depth backstop: the pre-checks above should already have caught
            # anything that would trip MarketData's own invariants. If this ever fires, it
            # means a rule exists in the domain model that this pipeline's pre-validation does
            # not yet mirror, and that gap should be closed rather than silently swallowed.
            rejected.append(
                RejectedRecord(
                    raw_id=obs.raw_id,
                    source_row_ref=obs.source_row_ref,
                    reason_code="DOMAIN_MODEL_REJECTED",
                    reasons=(str(exc),),
                )
            )
            continue

        accepted.append(market_data)
        if isin not in instruments:
            instruments[isin] = Instrument(
                isin=isin,
                symbol=symbol,
                exchange=_ADAPTER_EXCHANGE,
                lot_size=_EQUITY_LOT_SIZE,
                segment="EQUITY",
            )

    return NormalizationResult(
        data_snapshot_version=snapshot_version,
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        instruments=tuple(instruments.values()),
    )
