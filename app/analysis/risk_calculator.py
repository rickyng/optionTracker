from __future__ import annotations

from datetime import date

from app.schemas.position import Position
from app.schemas.risk import RiskMetrics
from app.schemas.strategy import StrategyType


def calculate_risk(
    strategy_type: StrategyType,
    legs: list[Position],
) -> RiskMetrics:
    """Calculate risk metrics for a detected strategy."""
    if not legs:
        return RiskMetrics()

    # Guard against zero/missing multiplier (default to standard 100)
    for leg in legs:
        if not leg.multiplier:
            leg.multiplier = 100

    days = _days_to_expiry(legs[0].expiry)

    match strategy_type:
        case StrategyType.NAKED_SHORT_PUT:
            return _naked_short_put(legs, days)
        case StrategyType.NAKED_SHORT_CALL:
            return _naked_short_call(legs, days)
        case StrategyType.BULL_PUT_SPREAD:
            return _bull_put_spread(legs, days)
        case StrategyType.BEAR_CALL_SPREAD:
            return _bear_call_spread(legs, days)
        case StrategyType.IRON_CONDOR:
            return _iron_condor(legs, days)
        case StrategyType.STRADDLE:
            return _straddle(legs, days)
        case StrategyType.STRANGLE:
            return _strangle(legs, days)
        case _:
            return RiskMetrics(days_to_expiry=days)


def _days_to_expiry(expiry: str) -> int:
    try:
        parts = expiry.split("-")
        exp_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        delta = (exp_date - date.today()).days
        return max(delta, 0)
    except (ValueError, IndexError):
        return 0


def _naked_short_put(legs: list[Position], days: int) -> RiskMetrics:
    pos = legs[0]
    qty = abs(pos.quantity)
    mult = pos.multiplier
    premium = pos.entry_premium
    net_premium = qty * premium * mult
    breakeven = pos.strike - premium
    max_loss = breakeven * mult * qty
    return RiskMetrics(
        breakeven_price=breakeven,
        max_profit=net_premium,
        max_loss=max_loss,
        risk_level="HIGH",
        net_premium=net_premium,
        days_to_expiry=days,
    )


def _naked_short_call(legs: list[Position], days: int) -> RiskMetrics:
    pos = legs[0]
    qty = abs(pos.quantity)
    mult = pos.multiplier
    premium = pos.entry_premium
    net_premium = qty * premium * mult
    breakeven = pos.strike + premium
    return RiskMetrics(
        breakeven_price=breakeven,
        max_profit=net_premium,
        max_loss=float("inf"),
        risk_level="HIGH",
        net_premium=net_premium,
        days_to_expiry=days,
    )


def _bull_put_spread(legs: list[Position], days: int) -> RiskMetrics:
    short_leg = max(legs, key=lambda p: p.strike)
    long_leg = min(legs, key=lambda p: p.strike)
    mult = short_leg.multiplier
    short_premium = abs(short_leg.quantity) * short_leg.entry_premium * mult
    long_premium = abs(long_leg.quantity) * long_leg.entry_premium * mult
    net_premium = short_premium - long_premium
    strike_diff = short_leg.strike - long_leg.strike
    breakeven = short_leg.strike - (net_premium / (abs(short_leg.quantity) * mult))
    max_loss = (strike_diff * mult * abs(short_leg.quantity)) - net_premium
    return RiskMetrics(
        breakeven_price=breakeven,
        max_profit=net_premium,
        max_loss=max_loss,
        risk_level="DEFINED",
        net_premium=net_premium,
        days_to_expiry=days,
    )


def _bear_call_spread(legs: list[Position], days: int) -> RiskMetrics:
    short_leg = min(legs, key=lambda p: p.strike)
    long_leg = max(legs, key=lambda p: p.strike)
    mult = short_leg.multiplier
    short_premium = abs(short_leg.quantity) * short_leg.entry_premium * mult
    long_premium = abs(long_leg.quantity) * long_leg.entry_premium * mult
    net_premium = short_premium - long_premium
    strike_diff = long_leg.strike - short_leg.strike
    breakeven = short_leg.strike + (net_premium / (abs(short_leg.quantity) * mult))
    max_loss = (strike_diff * mult * abs(short_leg.quantity)) - net_premium
    return RiskMetrics(
        breakeven_price=breakeven,
        max_profit=net_premium,
        max_loss=max_loss,
        risk_level="DEFINED",
        net_premium=net_premium,
        days_to_expiry=days,
    )


def _iron_condor(legs: list[Position], days: int) -> RiskMetrics:
    puts = [p for p in legs if p.right == "P"]
    calls = [p for p in legs if p.right == "C"]
    mult = legs[0].multiplier if legs else 100

    # Short legs have negative quantity
    short_puts = [p for p in puts if p.quantity < 0]
    long_puts = [p for p in puts if p.quantity > 0]
    short_calls = [p for p in calls if p.quantity < 0]
    long_calls = [p for p in calls if p.quantity > 0]

    total_short_premium = sum(abs(p.quantity) * p.entry_premium * mult for p in short_puts + short_calls)
    total_long_premium = sum(abs(p.quantity) * p.entry_premium * mult for p in long_puts + long_calls)
    net_premium = total_short_premium - total_long_premium
    net_premium_per_share = net_premium / mult

    # Short put = highest strike put with negative qty
    short_put_strike = max(p.strike for p in short_puts) if short_puts else 0
    # Short call = lowest strike call with negative qty
    short_call_strike = min(c.strike for c in short_calls) if short_calls else 0

    breakeven_1 = short_put_strike - net_premium_per_share
    breakeven_2 = short_call_strike + net_premium_per_share

    put_strikes = sorted(p.strike for p in puts)
    call_strikes = sorted(c.strike for c in calls)
    put_spread_width = put_strikes[-1] - put_strikes[0] if len(put_strikes) >= 2 else 0
    call_spread_width = call_strikes[-1] - call_strikes[0] if len(call_strikes) >= 2 else 0
    max_loss = max(put_spread_width, call_spread_width) * mult - net_premium

    return RiskMetrics(
        breakeven_price=breakeven_1,
        breakeven_price_2=breakeven_2,
        max_profit=net_premium,
        max_loss=max_loss,
        risk_level="DEFINED",
        net_premium=net_premium,
        days_to_expiry=days,
    )


def _straddle(legs: list[Position], days: int) -> RiskMetrics:
    mult = legs[0].multiplier if legs else 100
    total_premium = sum(abs(p.quantity) * p.entry_premium * mult for p in legs)
    strike = legs[0].strike
    return RiskMetrics(
        breakeven_price=strike - total_premium / mult,
        breakeven_price_2=strike + total_premium / mult,
        max_profit=float("inf"),
        max_loss=total_premium,
        risk_level="MEDIUM",
        net_premium=total_premium,
        days_to_expiry=days,
    )


def _strangle(legs: list[Position], days: int) -> RiskMetrics:
    mult = legs[0].multiplier if legs else 100
    total_premium = sum(abs(p.quantity) * p.entry_premium * mult for p in legs)
    puts = [p for p in legs if p.right == "P"]
    calls = [p for p in legs if p.right == "C"]
    put_strike = puts[0].strike if puts else 0
    call_strike = calls[0].strike if calls else 0
    return RiskMetrics(
        breakeven_price=put_strike - total_premium / mult,
        breakeven_price_2=call_strike + total_premium / mult,
        max_profit=float("inf"),
        max_loss=total_premium,
        risk_level="MEDIUM",
        net_premium=total_premium,
        days_to_expiry=days,
    )
