"""Metrics appropriate to declared forecast type. No p-values are manufactured."""

from __future__ import annotations

import math
from collections.abc import Sequence


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = hits / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman_ic(scores: Sequence[float], returns: Sequence[float]) -> float | None:
    if len(scores) != len(returns) or len(scores) < 3:
        return None
    a, b = _ranks(scores), _ranks(returns)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return None if da == 0 or db == 0 else num / (da * db)


def brier(ps: Sequence[float], outcomes: Sequence[int]) -> float | None:
    return sum((p - o) ** 2 for p, o in zip(ps, outcomes, strict=True)) / len(ps) if ps else None


def log_loss(ps: Sequence[float], outcomes: Sequence[int]) -> float | None:
    if not ps:
        return None
    eps = 1e-12
    return -sum(
        o * math.log(min(max(p, eps), 1 - eps)) + (1 - o) * math.log(min(max(1 - p, eps), 1 - eps))
        for p, o in zip(ps, outcomes, strict=True)
    ) / len(ps)
