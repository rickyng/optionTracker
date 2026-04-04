from __future__ import annotations

from pydantic import BaseModel


class RiskMetrics(BaseModel):
    breakeven_price: float = 0.0
    breakeven_price_2: float = 0.0  # For iron condors
    max_profit: float = 0.0
    max_loss: float = 0.0  # float('inf') for unlimited
    risk_level: str = ""  # "LOW", "MEDIUM", "HIGH", "DEFINED"
    net_premium: float = 0.0
    days_to_expiry: int = 0


class AccountRisk(BaseModel):
    account_id: int
    account_name: str
    position_count: int
    strategy_count: int
    max_profit: float = 0.0
    max_loss: float = 0.0
    capital_at_risk: float = 0.0
    net_premium: float = 0.0
    expiring_soon: int = 0  # < 7 days


class PortfolioRisk(BaseModel):
    total_max_profit: float = 0.0
    total_max_loss: float = 0.0
    total_capital_at_risk: float = 0.0
    positions_expiring_soon: int = 0  # < 7 days
    total_strategies: int = 0
    account_risks: list[AccountRisk] = []
