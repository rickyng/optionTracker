"""Compute underlying-level exposure summary for dashboard overview.

Pure function — no I/O, no DB access. Takes data objects and returns a dict.
"""

from __future__ import annotations

from collections import defaultdict

from app.schemas.position import Position
from app.schemas.strategy import Strategy


def compute_underlying_exposure(
    positions: list[Position],
    strategies: list[Strategy],
    account_names: dict[int, str],
    market_prices: dict[str, float | None],
    risk_factor: float,
    earnings_dates: dict[str, str | None] | None = None,
) -> dict:
    """Compute dashboard summary for a single risk margin percentage.

    Returns a dict with total_est_profit, total_est_loss, underlying_exposure, etc.
    Note: float('inf') values may be present — the caller should sanitize for JSON.
    """
    underlying_exp: dict[str, dict] = defaultdict(
        lambda: {
            "est_profit": 0.0,
            "est_loss": 0.0,
            "call_loss": 0.0,
            "put_loss": 0.0,
            "has_calls": False,
            "has_puts": False,
            "market_price": None,
            "price_unavailable": False,
            "earnings_date": None,
            "positions": [],
        }
    )

    for p in positions:
        exp = underlying_exp[p.underlying]
        if exp["earnings_date"] is None and earnings_dates:
            exp["earnings_date"] = earnings_dates.get(p.underlying)
        mult = p.multiplier
        qty = abs(p.quantity)
        premium = p.entry_premium

        pos_profit = qty * premium * mult
        pos_loss = 0.0
        margin_price = None
        market_price = market_prices.get(p.underlying)
        if market_price is not None:
            if p.right == "P":
                margin_price = round(market_price * (1 - risk_factor), 2)
                loss_per_share = p.strike - margin_price
            else:
                margin_price = round(market_price * (1 + risk_factor), 2)
                loss_per_share = margin_price - p.strike
            pos_loss = max(0, loss_per_share) * mult * qty
            exp["market_price"] = market_price
        else:
            exp["price_unavailable"] = True

        exp["est_profit"] += pos_profit

        if p.right == "C":
            exp["call_loss"] += pos_loss
            exp["has_calls"] = True
        else:
            exp["put_loss"] += pos_loss
            exp["has_puts"] = True

        exp["positions"].append(
            {
                "account": account_names.get(p.account_id, str(p.account_id)),
                "expiry": p.expiry,
                "strike": p.strike,
                "right": p.right,
                "quantity": p.quantity,
                "risk_margin_price": margin_price,
                "est_profit": round(pos_profit, 2),
                "est_loss": round(pos_loss, 2),
                "price_unavailable": market_price is None,
            }
        )

    for exp_data in underlying_exp.values():
        if exp_data["has_calls"] and exp_data["has_puts"]:
            exp_data["est_loss"] = round(max(exp_data["call_loss"], exp_data["put_loss"]), 2)
        else:
            exp_data["est_loss"] = round(exp_data["call_loss"] + exp_data["put_loss"], 2)

    total_premium = sum(
        sum(leg.get("entry_premium", 0) * abs(leg.get("quantity", 0)) * leg.get("multiplier", 100) for leg in s.legs)
        for s in strategies
    )

    return {
        "total_accounts": len({p.account_id for p in positions}) if positions else 0,
        "total_positions": len(positions),
        "total_strategies": len(strategies),
        "total_est_profit": sum(e["est_profit"] for e in underlying_exp.values()),
        "total_est_loss": sum(e["est_loss"] for e in underlying_exp.values()),
        "total_net_premium": total_premium,
        "underlying_exposure": dict(underlying_exp),
    }
