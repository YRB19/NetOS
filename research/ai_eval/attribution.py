"""AI-specific metrics and attribution (Slice 12). Pure functions over plain data."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from research.ai_eval.pit_audit import PitAuditReport
from research.ai_eval.stats import BootstrapCI, mean_ci_iid
from shared.time.clock import ensure_utc

_DROP = ("idempotency", "candidate", "rationale", "confidence")


def _canon(o):
    if isinstance(o, Mapping):
        return {k: _canon(v) for k, v in o.items()
                if not (k.endswith("_id") or k.endswith("_ids") or any(x in k for x in _DROP))}  # fmt: skip
    if isinstance(o, (list, tuple)):
        return [_canon(v) for v in o]
    return o


def canonical_trades(trades: Iterable[Mapping]) -> list[str]:
    """Economic content of trades/fills with identity and AI-provenance keys removed, sorted."""
    return sorted(json.dumps(_canon(t), sort_keys=True, default=str) for t in trades)


def incremental_trades(base: Iterable[Mapping], ai: Iterable[Mapping]) -> dict:
    """Trades present in one arm but not the other (multiset difference)."""
    cb, ca = Counter(canonical_trades(base)), Counter(canonical_trades(ai))
    only_ai, only_base = ca - cb, cb - ca
    return {"baseline_trade_count": sum(cb.values()), "ai_trade_count": sum(ca.values()),
            "trades_only_in_ai_arm": sum(only_ai.values()),
            "trades_only_in_baseline_arm": sum(only_base.values()),
            "identical": not only_ai and not only_base}  # fmt: skip


def signal_metrics(signals: Sequence[Mapping], audit: PitAuditReport, overlay_provenance: Sequence[Mapping],
                   trade_candidate_keys: frozenset[tuple[str, str]], disclosure_status_counts: Mapping[str, int]) -> dict:  # fmt: skip
    """Counts and rates; every denominator is stated. Nothing is a calibrated probability."""
    n = len(signals)
    st = Counter(str(s.get("provider_status")) for s in signals)
    docs = {d for s in signals for d in (s.get("document_ids") or ())}
    elig_sig = [s for s, e in zip(signals, audit.entries, strict=True) if e.eligible]
    valid = [s for s in elig_sig if s.get("provider_status") == "OK"
             and (s.get("interpretation") or {}).get("status") == "SIGNAL"]  # fmt: skip
    n_trade_candidates = len(trade_candidate_keys)
    valid_on_trades = [s for s in valid if (s["instrument_id"], ensure_utc(_pt(s["decision_timestamp"])).isoformat())
                       in trade_candidate_keys]  # fmt: skip
    applied = [p for p in overlay_provenance if p.get("applied") in (True, "True", "true")]
    deltas = [abs(float(p["confidence_delta"])) for p in applied]
    dirs = Counter(str((s.get("interpretation") or {}).get("confidence_adjustment")) for s in valid)
    reasons = Counter(str(p.get("outcome_reason")) for p in overlay_provenance)

    def rate(x: int, d: int) -> dict:
        return {"numerator": x, "denominator": d, "value": (x / d) if d else None}

    # stability: share of consecutive same-instrument signals that keep the same direction
    by_inst: dict[str, list[str]] = {}
    for s in sorted(valid, key=lambda s: (s["instrument_id"], str(s["decision_timestamp"]))):
        by_inst.setdefault(s["instrument_id"], []).append(
            str((s.get("interpretation") or {}).get("confidence_adjustment")))  # fmt: skip
    pairs = [(a, b) for v in by_inst.values() for a, b in zip(v, v[1:], strict=False)]
    return {
        "disclosures_referenced_by_signals": len(docs),
        "disclosure_store_status_counts": dict(disclosure_status_counts),
        "signals_total": n,
        "signals_eligible_after_pit_audit": len(elig_sig),
        "signals_rejected_by_pit_audit": n - len(elig_sig),
        "valid_ai_signals": len(valid),
        "provider_failure_rate": rate(sum(v for k, v in st.items() if k not in ("OK", "DISABLED", "EMPTY_CONTEXT")), n),
        "invalid_schema_rate": rate(st.get("MALFORMED_OUTPUT", 0), n),
        "missing_provenance_rate": rate(sum(1 for e in audit.entries if "SNAPSHOT_ID_MISSING" in e.reasons), n),
        "signal_coverage": rate(len(valid_on_trades), n_trade_candidates),
        "signal_coverage_definition": "valid, eligible signals on BUY/SELL candidates / BUY/SELL candidates",
        "provider_status_counts": dict(sorted(st.items())),
        "adjustments_applied": len(applied),
        "adjustment_outcome_reasons": dict(sorted(reasons.items())),
        "mean_abs_adjustment": (sum(deltas) / len(deltas)) if deltas else None,
        "max_abs_adjustment": max(deltas) if deltas else None,
        "adjustment_direction_distribution": dict(sorted(dirs.items())),
        "signal_direction_stability": rate(sum(1 for a, b in pairs if a == b), len(pairs)),
        "confidence_interpretation": "model confidence is NOT a calibrated probability (calibration not demonstrated)",
    }  # fmt: skip


def _pt(v):  # noqa: ANN001, ANN202
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def _open_after(bars: Sequence, ts: datetime) -> float | None:
    for b in bars:  # bars sorted ascending
        if ensure_utc(b.timestamp) > ts:
            return float(b.open)
    return None


def information_content(rows: Sequence[Mapping], market_data: Sequence, decision_timestamps: Sequence[datetime], *,
                        confidence: Decimal, resamples: int, seed: int, min_n: int) -> dict:  # fmt: skip
    """Does the AI signal's direction line up with the instrument's next-cycle return?

    rows: {instrument_id, decision_timestamp, direction (+1 INCREASE / -1 DECREASE, relative to a long
    thesis), applied (bool)}. Forward return = next-bar-open after the decision to next-bar-open after
    the next decision timestamp (the repository's execution convention). This is a DIAGNOSTIC of signal
    information, independent of sizing. It is exploratory unless the evidence class is confirmatory-grade.
    """
    by_inst: dict[str, list] = {}
    for m in market_data:
        by_inst.setdefault(m.instrument_id, []).append(m)
    for v in by_inst.values():
        v.sort(key=lambda b: b.timestamp)
    ts_sorted = sorted(ensure_utc(t) for t in set(decision_timestamps))
    nxt = {t: ts_sorted[i + 1] for i, t in enumerate(ts_sorted[:-1])}
    infl: list[float] = []
    ctrl: list[float] = []
    aligned: list[float] = []
    dropped = 0
    for r in rows:
        t = ensure_utc(r["decision_timestamp"])
        if t not in nxt:
            dropped += 1
            continue
        bars = by_inst.get(r["instrument_id"], [])
        a, b = _open_after(bars, t), _open_after(bars, nxt[t])
        if a is None or b is None or a <= 0:
            dropped += 1
            continue
        ret = b / a - 1.0
        if r.get("applied") and r.get("direction"):
            infl.append(ret)
            aligned.append(float(r["direction"]) * ret)
        else:
            ctrl.append(ret)
    ci = mean_ci_iid(aligned, confidence=confidence, resamples=resamples, seed=seed, min_n=min_n)
    return {
        "n_influenced": len(infl), "n_non_influenced": len(ctrl), "n_dropped_no_forward_bar": dropped,
        "mean_forward_return_influenced": (sum(infl) / len(infl)) if infl else None,
        "mean_forward_return_non_influenced": (sum(ctrl) / len(ctrl)) if ctrl else None,
        "direction_aligned_return": ci.to_dict(),
        "hit_rate_direction_aligned": (sum(1 for x in aligned if x > 0) / len(aligned)) if aligned else None,
        "interpretation": ("positive aligned return = the signal's stated direction preceded same-direction "
                           "next-cycle returns; a diagnostic of information, not of tradable profit"),
        "limitations": ["cross-sectional observations share dates and are not independent (iid bootstrap is optimistic)",
                        "no adjustment for the baseline strategy's own selection effect"],
    }  # fmt: skip


__all__ = ["BootstrapCI", "canonical_trades", "incremental_trades", "information_content", "signal_metrics"]
