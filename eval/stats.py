"""Small statistics helpers for the eval scripts."""
from math import sqrt


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n (better than the plain normal one for small n and rates near 0 or 1)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def with_ci(k: int, n: int) -> str:
    """'k/n = 53.3% (95% CI 35.5-70.6%)'"""
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {pct(k / n if n else 0)} (95% CI {100 * lo:.1f}-{100 * hi:.1f}%)"
