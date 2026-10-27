"""Versioned regime segmentation (Slice 9, ADR-18).

Thresholds are REQUIRED inputs (no defaults, never tuned to results). Labels at time t use
only the index series up to t (decision-time valid). Returns are attributed to the label in
force at the START of the return period. Liquidity regimes are UNSUPPORTED: no verified
depth/spread data exists. The equal-weight index is a constructed descriptive series,
not an official index. Regimes with fewer samples than `min_samples` report INSUFFICIENT_SAMPLE.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from domain.models.market_data import MarketData


class RegimeDimension(str, Enum):  # noqa: UP042
    TREND = "TREND"
    VOLATILITY = "VOLATILITY"
    LIQUIDITY = "LIQUIDITY"


@dataclass(frozen=True)
class RegimeDefinition:
    regime_set_id: str
    version: int
    dimension: RegimeDimension
    lookback: int  # number of trailing index returns
    up_threshold: Decimal  # TREND: trailing cumulative return above -> RISING; VOL: high-vol level
    down_threshold: Decimal | None  # TREND: below -down -> FALLING (positive number); VOL: unused
    min_samples: int
    retrospective: bool = False  # True = labels may use whole-window info; descriptive only


def equal_weight_index(market_data: list[MarketData], instruments: set[str]) -> list[tuple[datetime, Decimal]]:
    """Level series (start 100) from average simple close-to-close return across instruments
    that have bars on both consecutive timestamps."""
    by_ts: dict[datetime, dict[str, Decimal]] = defaultdict(dict)
    for m in market_data:
        if m.instrument_id in instruments:
            by_ts[m.timestamp][m.instrument_id] = Decimal(str(m.close))
    ts = sorted(by_ts)
    if not ts:
        return []
    level = Decimal(100)
    out = [(ts[0], level)]
    for a, b in zip(ts, ts[1:], strict=False):
        rets = [by_ts[b][i] / by_ts[a][i] - 1 for i in by_ts[a] if i in by_ts[b]]
        if rets:
            level = level * (1 + sum(rets) / len(rets))
        out.append((b, level))
    return out


def _std(xs: list[Decimal]) -> Decimal:
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)).sqrt()


def classify(series: list[tuple[datetime, Decimal]], d: RegimeDefinition) -> dict[datetime, str]:
    if d.dimension is RegimeDimension.LIQUIDITY:
        return {t: "UNSUPPORTED_NO_VERIFIED_LIQUIDITY_INPUT" for t, _ in series}
    labels: dict[datetime, str] = {}
    levels = [v for _, v in series]
    for i, (t, _) in enumerate(series):
        if i < d.lookback:
            labels[t] = "UNCLASSIFIED_INSUFFICIENT_HISTORY"
            continue
        window = levels[i - d.lookback: i + 1]
        if d.dimension is RegimeDimension.TREND:
            cum = window[-1] / window[0] - 1
            if cum > d.up_threshold:
                labels[t] = "RISING"
            elif d.down_threshold is not None and cum < -d.down_threshold:
                labels[t] = "FALLING"
            else:
                labels[t] = "RANGE_BOUND"
        else:
            rets = [window[j + 1] / window[j] - 1 for j in range(len(window) - 1)]
            if len(rets) < 2:
                labels[t] = "UNCLASSIFIED_INSUFFICIENT_HISTORY"
            else:
                labels[t] = "HIGH_VOLATILITY" if _std(rets) > d.up_threshold else "LOW_VOLATILITY"
    return labels


def segment_equity(equity_curve: list[dict], labels: dict[datetime, str], d: RegimeDefinition) -> dict:
    """Per-regime compounded return and counts over the run's equity curve."""
    if d.dimension is RegimeDimension.LIQUIDITY:
        return {"status": "UNSUPPORTED", "reason": "no verified liquidity/depth input exists",
                "regime_set_id": d.regime_set_id, "version": d.version}  # fmt: skip
    buckets: dict[str, list[Decimal]] = defaultdict(list)
    for a, b in zip(equity_curve, equity_curve[1:], strict=False):
        ea, eb = Decimal(a["equity"]), Decimal(b["equity"])
        if ea == 0:
            continue
        lab = labels.get(a["timestamp"], "UNCLASSIFIED_NO_LABEL")
        buckets[lab].append(eb / ea - 1)
    out = {}
    for lab, rs in sorted(buckets.items()):
        comp = Decimal(1)
        for r in rs:
            comp *= 1 + r
        if lab.startswith("UNCLASSIFIED"):
            status = "UNCLASSIFIED"
        elif len(rs) < d.min_samples:
            status = "INSUFFICIENT_SAMPLE"
        else:
            status = "OK"
        out[lab] = {"status": status, "samples": len(rs),
                    "compounded_return": str(comp - 1) if status == "OK" else None,
                    "caveat": "regime labels classified " + ("retrospectively" if d.retrospective else "at decision time")}  # fmt: skip
    return {"status": "OK", "regime_set_id": d.regime_set_id, "version": d.version,
            "dimension": d.dimension.value, "lookback": d.lookback,
            "thresholds": {"up": str(d.up_threshold), "down": str(d.down_threshold) if d.down_threshold is not None else None},
            "min_samples": d.min_samples, "regimes": out}  # fmt: skip
