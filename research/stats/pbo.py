"""CSCV / Probability of Backtest Overfitting (Bailey, Borwein, Lopez de Prado, Zhu 2017).

Unit of analysis: a T x N matrix of aligned per-period returns, N candidate trials.
Method: split the T rows into S equal contiguous partitions (S even); for each of the
C(S, S/2) ways to pick S/2 partitions as in-sample (IS), the rest are out-of-sample (OOS).
n* = IS-best trial (metric MEAN_RETURN or SHARPE; ties -> lowest trial index, counted).
omega = rank_OOS(n*) / (N + 1)  (ascending, average rank for ties, best = N);
lambda = ln(omega / (1 - omega)).  PBO = share of combinations with lambda <= 0.
This is evidence about a defined testing setup, NOT proof of future profit.
Numerics: floats; ties/equality tolerance TIE_TOL = 1e-12. Never returns a default number.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from itertools import combinations

TIE_TOL = 1e-12
MAX_PARTITIONS = 16


class PboStatus(str, Enum):  # noqa: UP042
    OK = "OK"
    UNSUPPORTED = "UNSUPPORTED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True)
class PboResult:
    status: PboStatus
    reason: str | None
    pbo: float | None
    n_trials_supplied: int
    n_trials_used: int
    n_periods: int
    n_partitions: int
    n_combinations: int
    duplicate_trial_ids: tuple[str, ...]
    is_ties: int
    metric: str
    mean_logit: float | None
    prob_oos_loss_of_selected: float | None

    def to_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else (v.value if isinstance(v, Enum) else v))
                for k, v in self.__dict__.items()}  # fmt: skip


def _metric(vals: list[float], metric: str) -> float | None:
    n = len(vals)
    if n == 0:
        return None
    m = sum(vals) / n
    if metric == "MEAN_RETURN":
        return m
    if n < 2:
        return None
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    sd = math.sqrt(var)
    if sd < TIE_TOL:
        return None  # Sharpe undefined at zero variance
    return m / sd


def _avg_rank(values: list[float], idx: int) -> float:
    v = values[idx]
    below = sum(1 for x in values if x < v - TIE_TOL)
    ties = sum(1 for x in values if abs(x - v) <= TIE_TOL)
    return below + (ties + 1) / 2.0


def compute_pbo(returns: dict[str, Sequence[Decimal | float | None]], n_partitions: int = 8,
                metric: str = "SHARPE") -> PboResult:  # fmt: skip
    ids = list(returns)
    n_sup = len(ids)

    def bad(status: PboStatus, reason: str, **kw) -> PboResult:
        base = dict(n_trials_used=0, n_periods=0, n_partitions=n_partitions, n_combinations=0,
                    duplicate_trial_ids=(), is_ties=0, mean_logit=None, prob_oos_loss_of_selected=None)  # fmt: skip
        base.update(kw)
        return PboResult(status, reason, None, n_sup, metric=metric, **base)

    if metric not in ("SHARPE", "MEAN_RETURN"):
        return bad(PboStatus.UNSUPPORTED, f"unknown metric {metric!r}")
    if n_partitions < 4 or n_partitions % 2 or n_partitions > MAX_PARTITIONS:
        return bad(PboStatus.UNSUPPORTED, f"n_partitions must be even, in [4, {MAX_PARTITIONS}]")
    if n_sup < 2:
        return bad(PboStatus.INSUFFICIENT_SAMPLE, "at least 2 trials are required")
    lengths = {len(v) for v in returns.values()}
    if len(lengths) != 1:
        return bad(PboStatus.UNSUPPORTED, "return series are not aligned (different lengths)")
    T = lengths.pop()
    cols: dict[str, list[float]] = {}
    for k, series in returns.items():
        if any(x is None for x in series):
            return bad(PboStatus.UNSUPPORTED, f"missing return segment in trial {k!r}", n_periods=T)
        cols[k] = [float(x) for x in series]  # type: ignore[arg-type]
    if T % n_partitions:
        return bad(PboStatus.UNSUPPORTED, f"{T} periods not divisible by {n_partitions} partitions "
                   f"(no rows are silently dropped)", n_periods=T)  # fmt: skip
    rows = T // n_partitions
    if (n_partitions // 2) * rows < 2:
        return bad(PboStatus.INSUFFICIENT_SAMPLE, "fewer than 2 observations per half", n_periods=T)
    # identical candidates collapse to one (recorded; the ledger keeps the true trial count)
    seen: dict[tuple[float, ...], str] = {}
    dups: list[str] = []
    for k in ids:
        t = tuple(cols[k])
        if t in seen:
            dups.append(k)
        else:
            seen[t] = k
    used = [k for k in ids if k not in dups]
    if len(used) < 2:
        return bad(PboStatus.INSUFFICIENT_SAMPLE, "fewer than 2 distinct trials after removing identical candidates",
                   n_periods=T, duplicate_trial_ids=tuple(dups), n_trials_used=len(used))  # fmt: skip
    parts = [list(range(i * rows, (i + 1) * rows)) for i in range(n_partitions)]
    logits: list[float] = []
    is_ties = 0
    oos_loss = 0
    combos = list(combinations(range(n_partitions), n_partitions // 2))
    for c in combos:
        is_rows = [r for p in c for r in parts[p]]
        oos_rows = [r for p in range(n_partitions) if p not in c for r in parts[p]]
        is_perf, oos_perf = [], []
        for k in used:
            a = _metric([cols[k][r] for r in is_rows], metric)
            b = _metric([cols[k][r] for r in oos_rows], metric)
            if a is None or b is None:
                return bad(PboStatus.UNSUPPORTED, f"metric {metric} undefined (zero variance) for trial {k!r}",
                           n_periods=T, duplicate_trial_ids=tuple(dups), n_trials_used=len(used))  # fmt: skip
            is_perf.append(a)
            oos_perf.append(b)
        best = max(is_perf)
        winners = [i for i, v in enumerate(is_perf) if abs(v - best) <= TIE_TOL]
        if len(winners) > 1:
            is_ties += 1
        star = winners[0]
        omega = _avg_rank(oos_perf, star) / (len(used) + 1)
        logits.append(math.log(omega / (1 - omega)))
        if oos_perf[star] < 0:
            oos_loss += 1
    pbo = sum(1 for lam in logits if lam <= TIE_TOL * 0) / len(logits)
    return PboResult(PboStatus.OK, None, pbo, n_sup, len(used), T, n_partitions, len(combos),
                     tuple(dups), is_ties, metric, sum(logits) / len(logits), oos_loss / len(combos))  # fmt: skip
