from __future__ import annotations

from pydantic import BaseModel

from app.schemas.option import OptionParseResult


class TradeRecord(BaseModel):
    account_id: str
    trade_date: str
    symbol: str
    description: str
    underlying_symbol: str
    expiry: str
    strike: float = 0.0
    put_call: str
    quantity: float = 0.0
    trade_price: float = 0.0
    proceeds: float = 0.0
    commission: float = 0.0
    net_cash: float = 0.0
    asset_class: str
    option_details: OptionParseResult | None = None


class OpenPositionRecord(BaseModel):
    account_id: str
    symbol: str
    description: str
    underlying_symbol: str
    expiry: str
    strike: float = 0.0
    put_call: str
    quantity: float = 0.0
    multiplier: float = 100.0
    mark_price: float = 0.0
    position_value: float = 0.0
    open_price: float = 0.0
    cost_basis_price: float = 0.0
    cost_basis_money: float = 0.0
    unrealized_pnl: float = 0.0
    asset_class: str
    report_date: str
    option_details: OptionParseResult | None = None
