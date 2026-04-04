from __future__ import annotations

from collections import defaultdict

from app.analysis.risk_calculator import calculate_risk
from app.schemas.position import Position
from app.schemas.strategy import Strategy, StrategyType


def detect_strategies(
    positions: list[Position],
) -> list[Strategy]:
    """Group positions into strategies and compute risk metrics for each."""
    if not positions:
        return []

    # Group by (account_id, underlying, expiry)
    groups: dict[tuple[int, str, str], list[Position]] = defaultdict(list)
    for pos in positions:
        groups[(pos.account_id, pos.underlying, pos.expiry)].append(pos)

    strategies: list[Strategy] = []
    for (account_id, underlying, expiry), legs in groups.items():
        strategy_type = _classify(legs)
        account_name = legs[0].account_name if legs else ""
        risk = calculate_risk(strategy_type, legs)

        strategies.append(
            Strategy(
                type=strategy_type,
                underlying=underlying,
                expiry=expiry,
                legs=[_position_to_leg_dict(p) for p in legs],
                account_id=account_id,
                account_name=account_name,
                breakeven_price=risk.breakeven_price,
                max_profit=risk.max_profit,
                max_loss=risk.max_loss,
                risk_level=risk.risk_level,
            )
        )

    return strategies


def _classify(legs: list[Position]) -> StrategyType:
    """Classify a group of positions into a strategy type."""
    if not legs:
        return StrategyType.UNKNOWN

    puts = [p for p in legs if p.right == "P"]
    calls = [p for p in legs if p.right == "C"]

    # Single-leg strategies
    if len(legs) == 1:
        pos = legs[0]
        if pos.quantity < 0 and pos.right == "P":
            return StrategyType.NAKED_SHORT_PUT
        if pos.quantity < 0 and pos.right == "C":
            return StrategyType.NAKED_SHORT_CALL
        return StrategyType.UNKNOWN

    # Two-leg strategies
    if len(legs) == 2:
        # Straddle: same underlying, same strike, one put + one call
        if len(puts) == 1 and len(calls) == 1:
            if puts[0].strike == calls[0].strike:
                return StrategyType.STRADDLE
            # Strangle: different strikes
            return StrategyType.STRANGLE

        # Spread: both puts or both calls, one short + one long
        if len(puts) == 2:
            return StrategyType.BULL_PUT_SPREAD
        if len(calls) == 2:
            return StrategyType.BEAR_CALL_SPREAD

    # Four legs: iron condor
    if len(legs) == 4 and len(puts) == 2 and len(calls) == 2:
        return StrategyType.IRON_CONDOR

    return StrategyType.UNKNOWN


def _position_to_leg_dict(pos: Position) -> dict:
    return {
        "id": pos.id,
        "underlying": pos.underlying,
        "expiry": pos.expiry,
        "strike": pos.strike,
        "right": pos.right,
        "quantity": pos.quantity,
        "entry_premium": pos.entry_premium,
        "mark_price": pos.mark_price,
        "multiplier": pos.multiplier,
    }
