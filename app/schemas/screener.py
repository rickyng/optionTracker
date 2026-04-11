"""Pydantic schemas for the CSP Screener."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScanFilters(BaseModel):
    """Configurable screening thresholds."""

    min_iv: float = Field(default=0.30, description="Minimum implied volatility (decimal)")
    min_delta: float = Field(default=0.15, description="Minimum delta (absolute value)")
    max_delta: float = Field(default=0.35, description="Maximum delta (absolute value)")
    min_dte: int = Field(default=21, description="Minimum days to expiration")
    max_dte: int = Field(default=45, description="Maximum days to expiration")
    min_otm_pct: float = Field(default=5.0, description="Minimum OTM distance %")
    min_ann_roc: float = Field(default=12.0, description="Minimum annualized ROC %")
    max_capital: float = Field(default=50000.0, description="Maximum capital required per position")
    max_beta: float = Field(default=2.5, description="Maximum beta (filter out high-volatility)")


class ScreenerResultOut(BaseModel):
    """A single screened put opportunity."""

    symbol: str
    price: float
    strike: float
    expiry: str
    dte: int
    bid: float
    mid: float
    iv: float
    delta: float
    otm_pct: float
    ann_roc_pct: float
    capital_required: float
    pe_ratio: float | None
    beta: float | None
    profit_margin: float | None
    revenue_growth: float | None
    strong_fundamentals: bool
    rating: int
    rating_label: str


class ScanResponse(BaseModel):
    """Response from a scan request."""

    scanned_at: str
    watchlist_count: int
    opportunities_found: int
    failed_tickers: list[str]
    avg_iv: float
    total_capital: float
    results: list[ScreenerResultOut]


class WatchlistSymbol(BaseModel):
    symbol: str


class WatchlistOut(BaseModel):
    symbols: list[str]
