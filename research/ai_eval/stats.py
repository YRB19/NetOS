"""Deterministic statistics for the AI-vs-baseline evaluation (Slice 12).

Only methods that are statistically defensible for the data supplied. No p-values are produced:
the evidence standard is a seeded paired block-bootstrap confidence interval for the mean
per-cycle return difference, with the confidence level Bonferroni-adjusted for the number of
comparisons. Identical paths are reported as such (zero variance), never as "significant".
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal


def adjusted_confidence_level(family_level: Decimal, n_comparisons: int) -> Decimal:
    """Bonferroni: per-comparison two-sided level = 1 - (1 - family_level) / m."""
    if n_comparisons < 1:
        raise ValueError("n_comparisons must be >= 1")
    return Decimal(1) - (Decimal(1) - family_level) / Decimal(n_comparisons)


def cycle_returns(curve: Sequence[dict]) -> list[tuple[str, float]]:
    """Per-decision-cycle simple returns from an equity curve of {timestamp, equity}."""
    out: list[tuple[str, float]] = []
    prev: float | None = None
    for pt in curve:
        eq = float(pt["equity"])
        if prev is not None and prev > 0:
            out.append((str(pt["timestamp"]), eq / prev - 1.0))
        prev = eq
    return out


def paired_differences(a: Sequence[dict], b: Sequence[dict]) -> list[float]:
    """a - b per cycle, aligned on timestamp; refuses curves that do not align exactly."""
    ra, rb = cycle_returns(a), cycle_returns(b)
    if [t for t, _ in ra] != [t for t, _ in rb]:
        raise ValueError("equity curves are not aligned on identical timestamps; cannot pair")
    return [x - y for (_, x), (_, y) in zip(ra, rb, strict=True)]


@dataclass(frozen=True)
class BootstrapCI:
    status: str  # OK | ZERO_VARIANCE_IDENTICAL_PATHS | INSUFFICIENT_SAMPLE
    n: int
    mean: float | None
    lower: float | None
    upper: float | None
    confidence_level: str
    method: str
    seed: int
    resamples: int
    block_length: int
    reason: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def block_bootstrap_mean_ci(xs: Sequence[float], *, confidence: Decimal, resamples: int, block_length: int,
                            seed: int, min_n: int = 2) -> BootstrapCI:  # fmt: skip
    """Seeded circular moving-block bootstrap percentile CI for the mean."""
    n = len(xs)
    meth = "circular moving-block bootstrap, percentile interval"
    base = dict(n=n, confidence_level=str(confidence), method=meth, seed=seed, resamples=resamples,
                block_length=block_length)  # fmt: skip
    if n < min_n:
        return BootstrapCI("INSUFFICIENT_SAMPLE", mean=None, lower=None, upper=None,
                           reason=f"need at least {min_n} observations, have {n}", **base)  # fmt: skip
    mean = math.fsum(xs) / n
    if all(x == 0.0 for x in xs):
        return BootstrapCI("ZERO_VARIANCE_IDENTICAL_PATHS", mean=0.0, lower=0.0, upper=0.0,
                           reason="every paired difference is exactly zero: the two paths are identical", **base)  # fmt: skip
    rng = random.Random(seed)
    L = max(1, min(block_length, n))
    n_blocks = math.ceil(n / L)
    means: list[float] = []
    for _ in range(resamples):
        tot, cnt = 0.0, 0
        for _b in range(n_blocks):
            s = rng.randrange(n)
            for k in range(L):
                if cnt == n:
                    break
                tot += xs[(s + k) % n]
                cnt += 1
        means.append(tot / n)
    means.sort()
    alpha = (1.0 - float(confidence)) / 2.0
    lo = means[max(0, int(math.floor(alpha * resamples)))]
    hi = means[min(resamples - 1, int(math.ceil((1.0 - alpha) * resamples)) - 1)]
    return BootstrapCI("OK", mean=mean, lower=lo, upper=hi, **base)


def mean_ci_iid(xs: Sequence[float], *, confidence: Decimal, resamples: int, seed: int, min_n: int) -> BootstrapCI:
    """iid bootstrap for cross-sectional signal-level samples (block length 1)."""
    return block_bootstrap_mean_ci(xs, confidence=confidence, resamples=resamples, block_length=1,
                                   seed=seed, min_n=min_n)  # fmt: skip
