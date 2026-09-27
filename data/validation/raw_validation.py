"""Raw-level validation: does this raw observation have what the declared source schema
promises, before any field renaming/type-parsing happens?

Per Stage 3 §5 "Reject records missing required: instrument, timestamp, price fields, volume
where required, source metadata." This module is the historical-data-pipeline's mechanical
implementation of SF-1 (missing data) at the point closest to the source.
"""

from __future__ import annotations

from dataclasses import dataclass

from data.schemas.nse_bhavcopy_schema import ALLOWED_SERIES, REQUIRED_COLUMNS
from domain.models.raw_observation import RawMarketObservation


@dataclass(frozen=True)
class RawValidationResult:
    raw_id: str
    ok: bool
    reasons: tuple[str, ...]


def validate_raw_bhavcopy_observation(obs: RawMarketObservation) -> RawValidationResult:
    """Check that a raw bhavcopy-format observation has all required, non-empty fields, and
    that its SERIES value is one this pipeline is scoped to handle (TR-1: equity only).

    This function accumulates every problem found rather than stopping at the first one, so a
    single record's rejection reason is a complete diagnostic, not a partial one.
    """
    reasons: list[str] = []
    fields = obs.fields

    for column in REQUIRED_COLUMNS:
        value = fields.get(column)
        if value is None or str(value).strip() == "":
            reasons.append(f"missing required field: {column}")

    series = fields.get("SERIES")
    if series is not None and str(series).strip() != "":
        series_norm = str(series).strip().upper()
        if series_norm not in ALLOWED_SERIES:
            reasons.append(
                f"unsupported SERIES {series_norm!r}: only {sorted(ALLOWED_SERIES)} is in "
                f"scope per TR-1 (permitted-universe restriction to equity)"
            )

    return RawValidationResult(raw_id=obs.raw_id, ok=(len(reasons) == 0), reasons=tuple(reasons))
