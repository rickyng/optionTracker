from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class StrategyType(StrEnum):
    NAKED_SHORT_PUT = "naked_short_put"
    NAKED_SHORT_CALL = "naked_short_call"
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    IRON_CONDOR = "iron_condor"
    STRADDLE = "straddle"
    STRANGLE = "strangle"
    UNKNOWN = "unknown"


class Strategy(BaseModel):
    type: StrategyType
    underlying: str
    expiry: str
    legs: list[dict]  # Simplified leg representation
    account_id: int
    account_name: str = ""
    breakeven_price: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    risk_level: str = ""
