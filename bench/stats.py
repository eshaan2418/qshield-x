"""Statistics helpers: exact binomial CIs, per-round conversion, threshold crossing."""

from __future__ import annotations

import math

from scipy.stats import beta


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    a = 1 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return lo, hi


def per_round(pl: float, rounds: int) -> float:
    """Per-round logical error rate from a block error rate (assuming independent rounds)."""
    if pl >= 0.5:
        return 0.5
    return 0.5 * (1 - (1 - 2 * pl) ** (1 / rounds))


def crossing(ps: list[float], a: list[float], b: list[float]) -> float | None:
    """p where curve a (smaller d) and b (larger d) cross, log-log linear interpolation.
    Returns None if they do not cross in the sampled range."""
    pts = [(p, x, y) for p, x, y in zip(ps, a, b) if x > 0 and y > 0]
    for (p0, a0, b0), (p1, a1, b1) in zip(pts, pts[1:]):
        f0 = math.log(b0) - math.log(a0)
        f1 = math.log(b1) - math.log(a1)
        if f0 < 0 <= f1:
            t = -f0 / (f1 - f0)
            return math.exp(math.log(p0) + t * (math.log(p1) - math.log(p0)))
    return None
