from __future__ import annotations

from pydantic import BaseModel


class OptionDetails(BaseModel):
    underlying: str
    expiry: str  # YYYY-MM-DD
    strike: float
    right: str  # Literal["C", "P"]
    original_symbol: str


class Position(BaseModel):
    id: int
    account_id: int
    account_name: str
    symbol: str
    underlying: str
    expiry: str  # YYYY-MM-DD
    strike: float
    right: str  # Literal["C", "P"]
    quantity: float
    mark_price: float
    entry_premium: float
    multiplier: int = 100
    is_manual: bool


class PositionCreate(BaseModel):
    account_id: int
    symbol: str
    underlying: str
    expiry: str
    strike: float
    right: str
    quantity: float
    mark_price: float = 0.0
    entry_premium: float = 0.0
    multiplier: int = 100
    notes: str = ""
