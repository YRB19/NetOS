"""Tier-2 momentum feature formation (Slice 6, Stage 3 §12; Plane 1).

Exact definition (see docs/tier2-momentum.md):

    momentum(i, t) = P_i(t - skip) / P_i(t - lookback) - 1

where `t` is the decision timestamp, `skip`/`lookback` are calendar months
(defaults 1 and 12, i.e. "12-1" momentum) and `P_i(d)` is the `close` of the last
observation of instrument `i` on or before the end of calendar day `d`. The most
recent `skip` month(s) are therefore EXCLUDED from the signal.

Rebalance flag (`is_rebalance_date`): 1.0 iff `t` is the FIRST distinct observation
timestamp (across all visible instruments) inside its calendar month, using only
observations at or before `t` (no look-ahead); else 0.0.

Look-ahead protection: the builder itself discards any record stamped after `t`
even if the caller passes one (defence in depth on top of the harness replay).
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from data.features.calendar import end_of_day, month_key, shift_months
from data.features.context_builder import DEFAULT_STALENESS_THRESHOLD, build_feature_snapshots
from data.features.universe import PermittedUniverse
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.market_data import MarketData
from shared.versioning.content_hash import hash_json_stable
from shared.versioning.versioning import make_version_id

FEATURE_MOMENTUM = "momentum"
FEATURE_PRICE_END = "momentum_price_end"
FEATURE_PRICE_START = "momentum_price_start"
FEATURE_REBALANCE = "is_rebalance_date"

FEATURE_SET_LABEL = "tier2_momentum_features_v1"


@dataclass(frozen=True)
class MomentumConfig:
    lookback_months: int = 12
    skip_months: int = 1
    max_price_gap_days: int = 10  # a lookup price older than this vs. its target date => missing

    def validate(self) -> list[str]:
        errs: list[str] = []
        for name in ("lookback_months", "skip_months", "max_price_gap_days"):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool):
                errs.append(f"{name} must be an int, got {v!r}")
        if not errs:
            if self.skip_months < 0:
                errs.append("skip_months must be >= 0")
            if self.lookback_months <= self.skip_months:
                errs.append("lookback_months must be greater than skip_months")
            if self.max_price_gap_days < 0:
                errs.append("max_price_gap_days must be >= 0")
        return errs

    def payload(self) -> dict:
        return {
            "lookback_months": self.lookback_months,
            "skip_months": self.skip_months,
            "max_price_gap_days": self.max_price_gap_days,
            "formula": "close(t-skip)/close(t-lookback)-1",
        }


def momentum_feature_set_id(config: MomentumConfig) -> str:
    return make_version_id(FEATURE_SET_LABEL, config.payload())


class MomentumFeatureBuilder:
    """Builds FeatureSnapshots carrying the momentum signal and rebalance flag."""

    def __init__(self, config: MomentumConfig | None = None) -> None:
        self.config = config or MomentumConfig()
        errs = self.config.validate()
        if errs:
            raise ValueError("invalid MomentumConfig: " + "; ".join(errs))
        self.feature_set_id = momentum_feature_set_id(self.config)

    def identity(self) -> dict:
        return {"builder": "MomentumFeatureBuilder", "feature_set_id": self.feature_set_id,
                **self.config.payload()}  # fmt: skip

    def build(
        self,
        visible: list[MarketData],
        universe: PermittedUniverse,
        as_of: datetime,
        *,
        market_data_snapshot_version: str,
        staleness_threshold: timedelta = DEFAULT_STALENESS_THRESHOLD,
        instrument_ids: Iterable[str] | None = None,
    ) -> list[FeatureSnapshot]:
        records = [r for r in visible if r.timestamp <= as_of]  # never consume the future
        base = build_feature_snapshots(
            records,
            universe,
            as_of,
            market_data_snapshot_version=market_data_snapshot_version,
            feature_set_id=self.feature_set_id,
            staleness_threshold=staleness_threshold,
            instrument_ids=instrument_ids,
        )
        by_inst: dict[str, list[MarketData]] = {}
        for r in records:
            by_inst.setdefault(r.instrument_id, []).append(r)
        for lst in by_inst.values():
            lst.sort(key=lambda r: r.timestamp)

        first_of_month = not any(
            r.timestamp < as_of and month_key(r.timestamp) == month_key(as_of) for r in records
        )
        end_t = end_of_day(shift_months(as_of, -self.config.skip_months))
        start_t = end_of_day(shift_months(as_of, -self.config.lookback_months))
        gap = timedelta(days=self.config.max_price_gap_days)

        out: list[FeatureSnapshot] = []
        for snap in base:
            values: dict[str, float] = {FEATURE_REBALANCE: 1.0 if first_of_month else 0.0}
            if snap.reference_price is not None:
                p_end = _last_on_or_before(by_inst.get(snap.instrument_id, []), end_t, gap)
                p_start = _last_on_or_before(by_inst.get(snap.instrument_id, []), start_t, gap)
                if p_end is not None and p_start is not None and p_start.close > 0:
                    values[FEATURE_MOMENTUM] = p_end.close / p_start.close - 1.0
                    values[FEATURE_PRICE_END] = float(p_end.close)
                    values[FEATURE_PRICE_START] = float(p_start.close)
            new_id = "snap_" + hash_json_stable([snap.snapshot_id, sorted(values.items())])[:24]
            out.append(replace(snap, feature_values=values, snapshot_id=new_id))
        return out


def _last_on_or_before(
    recs: list[MarketData], target: datetime, max_gap: timedelta
) -> MarketData | None:
    if not recs:
        return None
    idx = bisect.bisect_right([r.timestamp for r in recs], target)
    if idx == 0:
        return None
    rec = recs[idx - 1]
    if target - rec.timestamp > max_gap + timedelta(days=1):  # end-of-day target tolerance
        return None
    return rec
