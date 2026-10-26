"""Uncertainty and paired tests for the results tables."""

from __future__ import annotations

import math
import random


def bootstrap_ci(
    values: list[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float, float]:
    """(mean, low, high): a percentile bootstrap confidence interval for the mean."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(int((1 - alpha / 2) * n_boot), n_boot - 1)]
    return sum(values) / n, lo, hi


def mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from the discordant pairs (b: only A, c: only B)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def wilcoxon(x: list[float], y: list[float]) -> tuple[float, float]:
    """Wilcoxon signed-rank test on paired values: (statistic, two-sided p).

    All-zero differences give (0.0, 1.0)."""
    from scipy.stats import wilcoxon as scipy_wilcoxon

    diffs = [a - b for a, b in zip(x, y, strict=True)]
    if not any(diffs):
        return 0.0, 1.0
    result = scipy_wilcoxon(x, y, zero_method="wilcox")
    return float(result.statistic), float(result.pvalue)
