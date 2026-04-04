from __future__ import annotations

from pydantic import BaseModel


class OptionParseResult(BaseModel):
    underlying: str
    expiry: str  # YYYY-MM-DD
    strike: float
    right: str  # "C" or "P"
    original_symbol: str
