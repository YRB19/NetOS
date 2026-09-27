"""Numeric-sanity and OHLC-consistency validation for a *candidate* canonical record, applied
before MarketData is constructed.

MarketData.__post_init__ (domain/models/market_data.py) already enforces these same invariants
and will raise if violated — that remains in place as a defense-in-depth backstop (Stage 3 §21
milestone note: "this constraint lives in the type itself... giving defense in depth"). This
module exists so the normalization pipeline can accumulate *every* problem with a candidate
record (not just the first one a dataclass constructor happens to hit) and route the record to
quarantine with a complete, useful reason list, rather than crashing the whole ingestion batch
on the first bad row.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateOHLCV:
    """A parsed-but-not-yet-validated set of numeric fields, prior to MarketData construction."""

    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class MarketDataValidationResult:
    ok: bool
    reasons: tuple[str, ...]


def validate_ohlcv(candidate: CandidateOHLCV) -> MarketDataValidationResult:
    reasons: list[str] = []

    for name in ("open", "high", "low", "close"):
        value = getattr(candidate, name)
        if math.isnan(value):
            reasons.append(f"{name} is NaN")
            continue
        if math.isinf(value):
            reasons.append(f"{name} is infinite")
            continue
        if value <= 0:
            reasons.append(f"{name} must be > 0, got {value}")

    if candidate.volume < 0:
        reasons.append(f"volume must be >= 0, got {candidate.volume}")

    # Only check OHLC consistency if all four prices are individually sane numbers —
    # comparing against a NaN/Inf value would itself be meaningless.
    price_fields_sane = not any(
        math.isnan(v) or math.isinf(v)
        for v in (candidate.open, candidate.high, candidate.low, candidate.close)
    )
    if price_fields_sane:
        top = max(candidate.open, candidate.close, candidate.low)
        bottom = min(candidate.open, candidate.close, candidate.high)
        if candidate.high < top:
            reasons.append(f"OHLC inconsistency: high={candidate.high} < max(open,close,low)={top}")
        if candidate.low > bottom:
            reasons.append(
                f"OHLC inconsistency: low={candidate.low} > min(open,close,high)={bottom}"
            )

    return MarketDataValidationResult(ok=(len(reasons) == 0), reasons=tuple(reasons))
