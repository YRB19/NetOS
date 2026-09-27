"""Corporate-action adjustment.

Stage 3 §5 requires the pipeline to preserve the raw/adjusted distinction and states: "If
independent adjustment requires another data source that cannot yet be integrated, document
the limitation honestly and keep the pipeline interface ready for it."

**What is implemented in this slice:** the adjustment *math* for stock splits/bonuses (a
multiplicative price/volume adjustment applied to all observations strictly before a split's
effective date), as a pure, deterministic, independently-tested function. This is demonstrated
against a synthetic fixture (tests/fault_injection or tests/unit — see
tests/unit/test_corporate_actions.py), not against a real corporate-action feed.

**What is NOT implemented:** a live source of actual split/bonus/dividend events for Indian
equities (Stage 1 DR-2). No such source was integrated this slice (no network access; DR-2
sourcing is unresearched). Consequently, the production adapter path (data/adapters/
nse_bhavcopy_csv.py -> data/normalization/pipeline.py) calls this function with an empty
`splits` list by default, so every canonical MarketData record produced by this slice's actual
pipeline carries `adjusted=False` and is, correctly, the as-traded (unadjusted) series the
bhavcopy source itself provides. This is a documented limitation (see
docs/data-ingestion.md), not a silent gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from data.validation.market_data_validation import CandidateOHLCV


@dataclass(frozen=True)
class SplitAction:
    """One stock split or bonus event.

    ratio_from -> ratio_to describes "X old shares become Y new shares" (e.g. a classic 1-for-1
    bonus is ratio_from=1, ratio_to=2; a 1-for-5 split is ratio_from=1, ratio_to=5).
    Observations strictly BEFORE `effective_date` have their prices divided by, and their
    volume multiplied by, (ratio_to / ratio_from).
    """

    instrument_id: str
    effective_date: date
    ratio_from: float
    ratio_to: float

    def __post_init__(self) -> None:
        if self.ratio_from <= 0 or self.ratio_to <= 0:
            raise ValueError("SplitAction ratios must be positive numbers.")
        if not self.instrument_id or not self.instrument_id.strip():
            raise ValueError("SplitAction.instrument_id must be non-empty.")

    @property
    def factor(self) -> float:
        """Multiplicative factor applied to *prices* for pre-split observations (< 1.0 for a
        forward split/bonus, since post-split there are more, cheaper shares)."""
        return self.ratio_from / self.ratio_to


@dataclass(frozen=True)
class AdjustedCandidate:
    ohlcv: CandidateOHLCV
    adjusted: bool
    applied_splits: tuple[SplitAction, ...]


def apply_split_adjustment(
    instrument_id: str,
    observation_timestamp: datetime,
    candidate: CandidateOHLCV,
    splits: tuple[SplitAction, ...] = (),
) -> AdjustedCandidate:
    """Apply every split for `instrument_id` whose effective_date is strictly after the
    observation's date to the given candidate OHLCV, producing a split-adjusted candidate.

    Splits are applied in effective_date order so a series crossing multiple corporate actions
    is adjusted consistently, one factor per subsequent split, exactly as the classical
    "adjust everything before each split by that split's factor" convention requires.
    """
    applicable = tuple(
        sorted(
            (
                s
                for s in splits
                if s.instrument_id == instrument_id
                and s.effective_date > observation_timestamp.date()
            ),
            key=lambda s: s.effective_date,
        )
    )
    if not applicable:
        return AdjustedCandidate(ohlcv=candidate, adjusted=False, applied_splits=())

    price_factor = 1.0
    volume_factor = 1.0
    for split in applicable:
        price_factor *= split.factor
        volume_factor *= 1.0 / split.factor

    adjusted = CandidateOHLCV(
        open=candidate.open * price_factor,
        high=candidate.high * price_factor,
        low=candidate.low * price_factor,
        close=candidate.close * price_factor,
        volume=round(candidate.volume * volume_factor),
    )
    return AdjustedCandidate(ohlcv=adjusted, adjusted=True, applied_splits=applicable)
