"""Pure functions for option Greeks, screening metrics, and ratings.

No I/O — all functions are independently testable.
"""

from __future__ import annotations

from math import log, sqrt

from scipy.stats import norm


def black_scholes_put_delta(s: float, k: float, t: float, r: float = 0.05, sigma: float = 0.30) -> float:
    """Black-Scholes put delta.

    Args:
        s: Spot price of underlying
        k: Strike price
        t: Time to expiration in years (DTE / 365)
        r: Risk-free rate (default 5%)
        sigma: Implied volatility (decimal, e.g. 0.30)

    Returns:
        Put delta (negative, e.g. -0.25)
    """
    if t <= 0 or sigma <= 0:
        return -1.0 if s < k else 0.0

    d1 = (log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * sqrt(t))
    return norm.cdf(d1) - 1


def calc_otm_pct(price: float, strike: float) -> float:
    """OTM distance as percentage for a put."""
    if price == 0:
        return 0.0
    return (price - strike) / price * 100


def calc_ann_roc(premium: float, strike: float, dte: int) -> float:
    """Annualized return on capital for a cash-secured put."""
    if dte <= 0 or strike <= 0:
        return 0.0
    return (premium / strike) / dte * 365 * 100


def is_strong_fundamentals(pe_ratio: float | None, profit_margin: float | None, beta: float | None) -> bool:
    """Check if fundamentals meet quality criteria."""
    if pe_ratio is None or profit_margin is None or beta is None:
        return False
    return pe_ratio > 0 and profit_margin > 10 and beta < 1.5


def calc_rating(iv: float, delta: float, dte: int, ann_roc: float, strong_fundamentals: bool) -> tuple[int, str]:
    """Compute composite rating score and label."""
    pts = 0

    if iv >= 0.60:
        pts += 2
    elif iv >= 0.30:
        pts += 1
    else:
        pts -= 1

    if 0.20 <= delta <= 0.30:
        pts += 2
    elif delta < 0.15 or delta > 0.35:
        pts -= 1

    if 30 <= dte <= 45:
        pts += 2

    if ann_roc >= 20:
        pts += 2
    elif ann_roc >= 12:
        pts += 1

    if strong_fundamentals:
        pts += 1

    score = max(1, min(5, pts))
    label = {5: "STRONG", 4: "GOOD", 3: "OK", 2: "FAIR", 1: "POOR"}.get(score, "OK")
    return score, label


def passes_filters(
    iv: float,
    delta: float,
    dte: int,
    otm_pct: float,
    ann_roc: float,
    capital: float,
    max_capital: float,
    min_iv: float = 0.30,
    min_delta: float = 0.15,
    max_delta: float = 0.35,
    min_dte: int = 21,
    max_dte: int = 45,
    min_otm_pct: float = 5.0,
    min_ann_roc: float = 12.0,
) -> bool:
    """Check if a put opportunity passes all screening criteria."""
    return (
        iv >= min_iv
        and min_delta <= delta <= max_delta
        and min_dte <= dte <= max_dte
        and otm_pct >= min_otm_pct
        and ann_roc >= min_ann_roc
        and capital <= max_capital
    )
