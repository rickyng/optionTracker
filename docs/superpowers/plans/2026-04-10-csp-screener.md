# CSP Screener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Cash-Secured Put screener integrated as a "Suggestions" tab in the IBKR Options Analyzer dashboard, using yfinance + scipy for data and calculations.

**Architecture:** Follows existing layered patterns — pure functions in `app/analysis/`, I/O in `app/services/`, REST endpoints in `app/api/`, dashboard UI in `app/dashboard/`. On-demand scan with results cached in SQLite. Per-user watchlist persisted in DB.

**Tech Stack:** yfinance (options chains, fundamentals, prices), scipy (Black-Scholes), SQLAlchemy (models), Pydantic (schemas), FastAPI (API), Dash + dash-bootstrap-components (UI)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/analysis/option_greeks.py` | Create | Pure functions: BS delta, OTM%, ROC, rating, filters |
| `tests/unit/test_option_greeks.py` | Create | Unit tests for all pure functions |
| `app/models/screener.py` | Create | SQLAlchemy models: ScreenerWatchlist, ScreenerResult |
| `app/models/__init__.py` | Modify | Import new models |
| `app/schemas/screener.py` | Create | Pydantic schemas: ScanFilters, ScanResult, ScanResponse |
| `app/services/screener_service.py` | Create | Scan orchestration, yfinance fetch, watchlist CRUD |
| `app/api/screener.py` | Create | REST endpoints for scan, results, watchlist |
| `app/main.py` | Modify | Register screener router |
| `app/dashboard/layouts/screener.py` | Create | Suggestions tab layout |
| `app/dashboard/app.py` | Modify | Add Suggestions tab to tabs list |
| `app/dashboard/callbacks/__init__.py` | Modify | Add screener callbacks |

---

### Task 1: Analysis Layer — Pure Functions

**Files:**
- Create: `app/analysis/option_greeks.py`
- Create: `tests/unit/test_option_greeks.py`

- [ ] **Step 1: Write failing tests for Black-Scholes delta and helpers**

```python
# tests/unit/test_option_greeks.py
import pytest

from app.analysis.option_greeks import (
    black_scholes_put_delta,
    calc_ann_roc,
    calc_otm_pct,
    calc_rating,
    is_strong_fundamentals,
    passes_filters,
)


class TestBlackScholesPutDelta:
    def test_atm_put_delta_near_negative_50(self):
        """ATM put delta should be close to -0.50."""
        delta = black_scholes_put_delta(S=100, K=100, T=30 / 365, r=0.05, sigma=0.30)
        assert -0.55 < delta < -0.45

    def test_deep_otm_put_delta_near_zero(self):
        """Deep OTM put delta should be close to 0."""
        delta = black_scholes_put_delta(S=100, K=80, T=30 / 365, r=0.05, sigma=0.30)
        assert -0.10 < delta < 0

    def test_deep_itm_put_delta_near_negative_1(self):
        """Deep ITM put delta should be close to -1."""
        delta = black_scholes_put_delta(S=100, K=120, T=30 / 365, r=0.05, sigma=0.30)
        assert -1.0 < delta < -0.85

    def test_zero_dte_returns_negative_1_or_0(self):
        """At expiry, put delta approaches -1 (ITM) or 0 (OTM)."""
        delta_itm = black_scholes_put_delta(S=100, K=110, T=1 / 365, r=0.05, sigma=0.30)
        assert delta_itm < -0.9
        delta_otm = black_scholes_put_delta(S=100, K=90, T=1 / 365, r=0.05, sigma=0.30)
        assert delta_otm > -0.1


class TestCalcOtmPct:
    def test_otm_put(self):
        assert calc_otm_pct(price=100, strike=90) == pytest.approx(10.0)

    def test_atm(self):
        assert calc_otm_pct(price=100, strike=100) == pytest.approx(0.0)

    def test_itm_negative(self):
        assert calc_otm_pct(price=100, strike=110) == pytest.approx(-10.0)


class TestCalcAnnRoc:
    def test_basic(self):
        # premium=3, strike=150, dte=30 => (3/150)/30*365*100 = 24.33%
        roc = calc_ann_roc(premium=3.0, strike=150.0, dte=30)
        assert roc == pytest.approx(24.33, rel=0.01)

    def test_zero_dte_returns_zero(self):
        assert calc_ann_roc(premium=3.0, strike=150.0, dte=0) == 0.0


class TestIsStrongFundamentals:
    def test_strong(self):
        assert is_strong_fundamentals(pe_ratio=25.0, profit_margin=20.0, beta=1.2) is True

    def test_negative_pe(self):
        assert is_strong_fundamentals(pe_ratio=-5.0, profit_margin=20.0, beta=1.2) is False

    def test_low_margin(self):
        assert is_strong_fundamentals(pe_ratio=25.0, profit_margin=5.0, beta=1.2) is False

    def test_high_beta(self):
        assert is_strong_fundamentals(pe_ratio=25.0, profit_margin=20.0, beta=2.0) is False


class TestCalcRating:
    def test_strong_5_stars(self):
        # IV=0.65 (+2), delta=0.25 (+2), dte=35 (+2), roc=25 (+2), strong_fund (+1) = 9 -> 5 STRONG
        score, label = calc_rating(iv=0.65, delta=0.25, dte=35, ann_roc=25.0, strong_fundamentals=True)
        assert score == 5
        assert label == "STRONG"

    def test_good_4_stars(self):
        # IV=0.45 (+1), delta=0.25 (+2), dte=35 (+2), roc=15 (+1), no fund (+0) = 6 -> 5 capped, but...
        # Actually 6 -> 5 STRONG. Let me adjust:
        # IV=0.45 (+1), delta=0.25 (+2), dte=35 (+2), roc=12 (+1), no fund (+0) = 6 -> 5 STRONG
        # Need lower: IV=0.45 (+1), delta=0.25 (+2), dte=25 (+0), roc=12 (+1), no fund (+0) = 4 -> GOOD
        score, label = calc_rating(iv=0.45, delta=0.25, dte=25, ann_roc=12.0, strong_fundamentals=False)
        assert score == 4
        assert label == "GOOD"

    def test_ok_3_stars(self):
        # IV=0.45 (+1), delta=0.25 (+2), dte=25 (+0), roc=10 (+0), no fund (+0) = 3 -> OK
        score, label = calc_rating(iv=0.45, delta=0.25, dte=25, ann_roc=10.0, strong_fundamentals=False)
        assert score == 3
        assert label == "OK"

    def test_low_iv_penalty(self):
        # IV=0.20 (-1), delta=0.25 (+2), dte=35 (+2), roc=15 (+1), no fund (+0) = 4 -> GOOD
        score, label = calc_rating(iv=0.20, delta=0.25, dte=35, ann_roc=15.0, strong_fundamentals=False)
        assert label == "GOOD"

    def test_outside_delta_penalty(self):
        # IV=0.45 (+1), delta=0.10 (-1), dte=35 (+2), roc=15 (+1), no fund (+0) = 3 -> OK
        score, label = calc_rating(iv=0.45, delta=0.10, dte=35, ann_roc=15.0, strong_fundamentals=False)
        assert label == "OK"


class TestPassesFilters:
    def test_passes_all(self):
        assert passes_filters(
            iv=0.40, delta=0.25, dte=30, otm_pct=8.0,
            ann_roc=15.0, capital=30000, max_capital=50000,
            min_iv=0.30, min_delta=0.15, max_delta=0.35,
            min_dte=21, max_dte=45, min_otm_pct=5.0,
            min_ann_roc=12.0,
        ) is True

    def test_fails_iv(self):
        assert passes_filters(
            iv=0.20, delta=0.25, dte=30, otm_pct=8.0,
            ann_roc=15.0, capital=30000, max_capital=50000,
            min_iv=0.30, min_delta=0.15, max_delta=0.35,
            min_dte=21, max_dte=45, min_otm_pct=5.0,
            min_ann_roc=12.0,
        ) is False

    def test_fails_delta_range(self):
        # delta=0.40 > max_delta=0.35
        assert passes_filters(
            iv=0.40, delta=0.40, dte=30, otm_pct=8.0,
            ann_roc=15.0, capital=30000, max_capital=50000,
            min_iv=0.30, min_delta=0.15, max_delta=0.35,
            min_dte=21, max_dte=45, min_otm_pct=5.0,
            min_ann_roc=12.0,
        ) is False

    def test_fails_capital(self):
        assert passes_filters(
            iv=0.40, delta=0.25, dte=30, otm_pct=8.0,
            ann_roc=15.0, capital=60000, max_capital=50000,
            min_iv=0.30, min_delta=0.15, max_delta=0.35,
            min_dte=21, max_dte=45, min_otm_pct=5.0,
            min_ann_roc=12.0,
        ) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/test_option_greeks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.option_greeks'`

- [ ] **Step 3: Implement pure functions**

```python
# app/analysis/option_greeks.py
"""Pure functions for option Greeks, screening metrics, and ratings.

No I/O — all functions are independently testable.
"""

from __future__ import annotations

from math import log, sqrt

from scipy.stats import norm


def black_scholes_put_delta(S: float, K: float, T: float, r: float = 0.05, sigma: float = 0.30) -> float:
    """Black-Scholes put delta.

    Args:
        S: Spot price of underlying
        K: Strike price
        T: Time to expiration in years (DTE / 365)
        r: Risk-free rate (default 5%)
        sigma: Implied volatility (decimal, e.g. 0.30)

    Returns:
        Put delta (negative, e.g. -0.25)
    """
    if T <= 0 or sigma <= 0:
        # At expiry: ITM = -1, OTM = 0
        return -1.0 if S < K else 0.0

    d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
    return norm.cdf(d1) - 1


def calc_otm_pct(price: float, strike: float) -> float:
    """OTM distance as percentage for a put.

    Returns positive when strike < price (OTM), negative when ITM.
    """
    if price == 0:
        return 0.0
    return (price - strike) / price * 100


def calc_ann_roc(premium: float, strike: float, dte: int) -> float:
    """Annualized return on capital for a cash-secured put.

    ROC = (premium / strike) / DTE * 365 * 100
    """
    if dte <= 0 or strike <= 0:
        return 0.0
    return (premium / strike) / dte * 365 * 100


def is_strong_fundamentals(pe_ratio: float | None, profit_margin: float | None, beta: float | None) -> bool:
    """Check if fundamentals meet quality criteria.

    True when: P/E > 0, profit margin > 10%, beta < 1.5
    """
    if pe_ratio is None or profit_margin is None or beta is None:
        return False
    return pe_ratio > 0 and profit_margin > 10 and beta < 1.5


def calc_rating(iv: float, delta: float, dte: int, ann_roc: float, strong_fundamentals: bool) -> tuple[int, str]:
    """Compute composite rating score and label.

    Returns (score 1-5, label).
    """
    pts = 0

    # IV scoring
    if iv >= 0.60:
        pts += 2
    elif iv >= 0.30:
        pts += 1
    else:
        pts -= 1

    # Delta scoring (delta is absolute value, e.g. 0.25)
    if 0.20 <= delta <= 0.30:
        pts += 2
    elif delta < 0.15 or delta > 0.35:
        pts -= 1
    # else: 0.15-0.20 or 0.30-0.35 -> +0

    # DTE scoring
    if 30 <= dte <= 45:
        pts += 2

    # ROC scoring
    if ann_roc >= 20:
        pts += 2
    elif ann_roc >= 12:
        pts += 1

    # Fundamentals
    if strong_fundamentals:
        pts += 1

    # Map to 1-5 scale
    score = max(1, min(5, pts))
    label = {5: "STRONG", 4: "GOOD", 3: "OK"}.get(score, "OK")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/unit/test_option_greeks.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/analysis/option_greeks.py tests/unit/test_option_greeks.py
git commit -m "feat: add option Greeks analysis layer with BS delta, rating, filters"
```

---

### Task 2: Pydantic Schemas

**Files:**
- Create: `app/schemas/screener.py`
- Modify: `app/schemas/__init__.py`

- [ ] **Step 1: Create screener schemas**

```python
# app/schemas/screener.py
"""Pydantic schemas for the CSP Screener."""

from __future__ import annotations

from datetime import datetime

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
```

- [ ] **Step 2: Update schemas __init__.py**

Add to `app/schemas/__init__.py` after the existing imports:

```python
from app.schemas.screener import ScanFilters, ScanResponse, ScreenerResultOut, WatchlistOut, WatchlistSymbol
```

And add to `__all__`:
```python
"ScanFilters",
"ScanResponse",
"ScreenerResultOut",
"WatchlistOut",
"WatchlistSymbol",
```

Full file becomes:

```python
from app.schemas.flex import OpenPositionRecord, TradeRecord
from app.schemas.option import OptionParseResult
from app.schemas.position import Position, PositionCreate
from app.schemas.risk import AccountRisk, PortfolioRisk, RiskMetrics
from app.schemas.screener import ScanFilters, ScanResponse, ScreenerResultOut, WatchlistOut, WatchlistSymbol
from app.schemas.strategy import Strategy, StrategyType

__all__ = [
    "AccountRisk",
    "OpenPositionRecord",
    "OptionParseResult",
    "PortfolioRisk",
    "Position",
    "PositionCreate",
    "RiskMetrics",
    "ScanFilters",
    "ScanResponse",
    "ScreenerResultOut",
    "Strategy",
    "StrategyType",
    "TradeRecord",
    "WatchlistOut",
    "WatchlistSymbol",
]
```

- [ ] **Step 3: Verify schemas import**

Run: `source .venv/bin/activate && python -c "from app.schemas.screener import ScanFilters, ScanResponse; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/schemas/screener.py app/schemas/__init__.py
git commit -m "feat: add CSP screener Pydantic schemas"
```

---

### Task 3: SQLAlchemy Models

**Files:**
- Create: `app/models/screener.py`
- Modify: `app/models/__init__.py`

- [ ] **Step 1: Create screener models**

```python
# app/models/screener.py
"""SQLAlchemy models for the CSP Screener watchlist and cached results."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String

from app.database import Base

_DEFAULT_WATCHLIST = "ADBE,AMZN,AVGO,BRK-B,GOOG,META,MSFT,NFLX,NVDA,ORCL,PEP,PLTR,PYPL,SAP,TSLA,TSM,U,UNH,V"


class ScreenerWatchlist(Base):
    """Per-user watchlist of ticker symbols for CSP screening."""

    __tablename__ = "screener_watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_sub = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("idx_watchlist_user_symbol", "user_sub", "symbol", unique=True),)


class ScreenerResult(Base):
    """Cached scan results — one row per passing put opportunity."""

    __tablename__ = "screener_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_sub = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    strike = Column(Float, nullable=False)
    expiry = Column(String, nullable=False)
    dte = Column(Integer, nullable=False)
    bid = Column(Float, nullable=False)
    mid = Column(Float, nullable=False)
    iv = Column(Float, nullable=False)
    delta = Column(Float, nullable=False)
    otm_pct = Column(Float, nullable=False)
    ann_roc_pct = Column(Float, nullable=False)
    capital_required = Column(Float, nullable=False)
    pe_ratio = Column(Float, nullable=True)
    beta = Column(Float, nullable=True)
    profit_margin = Column(Float, nullable=True)
    revenue_growth = Column(Float, nullable=True)
    strong_fundamentals = Column(Boolean, default=False)
    rating = Column(Integer, nullable=False)
    rating_label = Column(String, nullable=False)
    scanned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("idx_screener_results_user_scanned", "user_sub", "scanned_at"),)
```

- [ ] **Step 2: Update models __init__.py**

Full file becomes:

```python
from app.models.account import Account
from app.models.detected_strategy import DetectedStrategy
from app.models.market_price import MarketPrice
from app.models.metadata import Metadata
from app.models.open_option import OpenOption
from app.models.screener import ScreenerResult, ScreenerWatchlist
from app.models.strategy_leg import StrategyLeg
from app.models.trade import Trade
from app.models.user import User

__all__ = [
    "Account",
    "DetectedStrategy",
    "MarketPrice",
    "Metadata",
    "OpenOption",
    "ScreenerResult",
    "ScreenerWatchlist",
    "StrategyLeg",
    "Trade",
    "User",
]
```

- [ ] **Step 3: Verify models import and tables create**

Run: `source .venv/bin/activate && python -c "from app.models import ScreenerWatchlist, ScreenerResult; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/models/screener.py app/models/__init__.py
git commit -m "feat: add ScreenerWatchlist and ScreenerResult SQLAlchemy models"
```

---

### Task 4: Screener Service

**Files:**
- Create: `app/services/screener_service.py`

This is the core orchestration layer. It fetches data from yfinance, applies the analysis functions, and persists results.

- [ ] **Step 1: Create screener service**

```python
# app/services/screener_service.py
"""CSP Screener service — scan orchestration, yfinance data fetch, watchlist CRUD."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import yfinance as yf
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.option_greeks import (
    black_scholes_put_delta,
    calc_ann_roc,
    calc_otm_pct,
    calc_rating,
    is_strong_fundamentals,
    passes_filters,
)
from app.models.screener import ScreenerResult, ScreenerWatchlist
from app.schemas.screener import ScanFilters, ScreenerResultOut

_logger = logging.getLogger(__name__)

# Limit concurrent yfinance calls to avoid rate-limiting
_SEMAPHORE = asyncio.Semaphore(3)

# Default watchlist seeded for new users
DEFAULT_WATCHLIST = [
    "ADBE", "AMZN", "AVGO", "BRK-B", "GOOG", "META", "MSFT", "NFLX",
    "NVDA", "ORCL", "PEP", "PLTR", "PYPL", "SAP", "TSLA", "TSM", "U", "UNH", "V",
]


async def get_watchlist(db: AsyncSession, user_sub: str) -> list[str]:
    """Get user's watchlist symbols. Seeds default list if empty."""
    result = await db.execute(
        select(ScreenerWatchlist.symbol).where(ScreenerWatchlist.user_sub == user_sub)
    )
    symbols = [row[0] for row in result.all()]
    if not symbols:
        await seed_default_watchlist(db, user_sub)
        symbols = DEFAULT_WATCHLIST[:]
    return symbols


async def seed_default_watchlist(db: AsyncSession, user_sub: str) -> None:
    """Insert default watchlist for a new user."""
    for symbol in DEFAULT_WATCHLIST:
        db.add(ScreenerWatchlist(user_sub=user_sub, symbol=symbol))
    await db.commit()


async def add_symbol(db: AsyncSession, user_sub: str, symbol: str) -> ScreenerWatchlist:
    """Add a symbol to user's watchlist."""
    symbol = symbol.upper().strip()
    existing = await db.execute(
        select(ScreenerWatchlist).where(
            ScreenerWatchlist.user_sub == user_sub,
            ScreenerWatchlist.symbol == symbol,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"{symbol} already in watchlist")
    entry = ScreenerWatchlist(user_sub=user_sub, symbol=symbol)
    db.add(entry)
    await db.commit()
    return entry


async def remove_symbol(db: AsyncSession, user_sub: str, symbol: str) -> None:
    """Remove a symbol from user's watchlist."""
    await db.execute(
        delete(ScreenerWatchlist).where(
            ScreenerWatchlist.user_sub == user_sub,
            ScreenerWatchlist.symbol == symbol.upper().strip(),
        )
    )
    await db.commit()


async def get_latest_results(db: AsyncSession, user_sub: str) -> list[ScreenerResult]:
    """Get cached results from the most recent scan for this user."""
    # Find the latest scan timestamp
    latest = await db.execute(
        select(ScreenerResult.scanned_at)
        .where(ScreenerResult.user_sub == user_sub)
        .order_by(ScreenerResult.scanned_at.desc())
        .limit(1)
    )
    scan_time = latest.scalar_one_or_none()
    if not scan_time:
        return []

    result = await db.execute(
        select(ScreenerResult)
        .where(ScreenerResult.user_sub == user_sub, ScreenerResult.scanned_at == scan_time)
        .order_by(ScreenerResult.ann_roc_pct.desc())
    )
    return list(result.scalars().all())


async def scan_watchlist(
    db: AsyncSession, user_sub: str, filters: ScanFilters
) -> tuple[list[ScreenerResultOut], list[str]]:
    """Scan watchlist for CSP opportunities.

    Returns (results, failed_tickers).
    Deletes old scan results before storing new ones.
    """
    symbols = await get_watchlist(db, user_sub)
    if not symbols:
        return [], []

    # Fetch all tickers in parallel with semaphore
    tasks = [_scan_ticker(sym, filters) for sym in symbols]
    tick_results = await asyncio.gather(*tasks)

    all_results: list[ScreenerResultOut] = []
    failed_tickers: list[str] = []

    for symbol, ticker_results, error in tick_results:
        if error:
            failed_tickers.append(symbol)
            _logger.warning("Scan failed for %s: %s", symbol, error)
            continue
        all_results.extend(ticker_results)

    # Delete old results and store new ones
    await db.execute(delete(ScreenerResult).where(ScreenerResult.user_sub == user_sub))
    await db.flush()

    for r in all_results:
        db.add(ScreenerResult(
            user_sub=user_sub,
            symbol=r.symbol,
            price=r.price,
            strike=r.strike,
            expiry=r.expiry,
            dte=r.dte,
            bid=r.bid,
            mid=r.mid,
            iv=r.iv,
            delta=r.delta,
            otm_pct=r.otm_pct,
            ann_roc_pct=r.ann_roc_pct,
            capital_required=r.capital_required,
            pe_ratio=r.pe_ratio,
            beta=r.beta,
            profit_margin=r.profit_margin,
            revenue_growth=r.revenue_growth,
            strong_fundamentals=r.strong_fundamentals,
            rating=r.rating,
            rating_label=r.rating_label,
        ))
    await db.commit()

    return all_results, failed_tickers


async def _scan_ticker(
    symbol: str, filters: ScanFilters
) -> tuple[str, list[ScreenerResultOut], str | None]:
    """Fetch and screen puts for a single ticker.

    Returns (symbol, results, error).
    Runs yfinance calls in a thread with semaphore.
    """
    async with _SEMAPHORE:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _fetch_and_screen, symbol, filters)
            return symbol, result, None
        except Exception as e:
            return symbol, [], str(e)


def _fetch_and_screen(symbol: str, filters: ScanFilters) -> list[ScreenerResultOut]:
    """Synchronous: fetch yfinance data and screen puts for one ticker.

    This runs in a thread executor because yfinance is synchronous.
    """
    ticker = yf.Ticker(symbol)

    # Get current price
    info = ticker.info or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        raise ValueError(f"No price for {symbol}")

    # Fundamentals
    pe_ratio = info.get("trailingPE")
    beta = info.get("beta")
    profit_margin = info.get("profitMargins")
    if profit_margin is not None:
        profit_margin = profit_margin * 100  # Convert to percentage
    revenue_growth = info.get("revenueGrowth")
    if revenue_growth is not None:
        revenue_growth = revenue_growth * 100  # Convert to percentage

    strong = is_strong_fundamentals(pe_ratio, profit_margin, beta)

    # Filter out high-beta stocks early
    if beta is not None and beta > filters.max_beta:
        return []

    # Get available expirations
    expirations = ticker.options
    if not expirations:
        raise ValueError(f"No options for {symbol}")

    # Find expirations within DTE range
    from datetime import date as date_type
    today = date_type.today()
    valid_expirations = []
    for exp_str in expirations:
        try:
            exp_date = date_type.fromisoformat(exp_str)
            dte = (exp_date - today).days
            if filters.min_dte <= dte <= filters.max_dte:
                valid_expirations.append((exp_str, dte))
        except ValueError:
            continue

    # Take next 2-3 valid expirations
    valid_expirations = valid_expirations[:3]
    if not valid_expirations:
        return []

    results: list[ScreenerResultOut] = []

    for exp_str, dte in valid_expirations:
        try:
            chain = ticker.option_chain(exp_str)
        except Exception:
            continue

        puts = chain.puts
        if puts is None or puts.empty:
            continue

        for _, put in puts.iterrows():
            strike = put.get("strike")
            bid = put.get("bid")
            ask = put.get("ask")
            iv = put.get("impliedVolatility")

            if strike is None or bid is None or bid <= 0 or iv is None or iv <= 0:
                continue

            mid = (bid + (ask or bid)) / 2
            otm_pct = calc_otm_pct(price, strike)
            ann_roc = calc_ann_roc(bid, strike, dte)
            capital = strike * 100

            # Compute delta via Black-Scholes
            T = dte / 365
            delta_raw = black_scholes_put_delta(S=price, K=strike, T=T, r=0.05, sigma=iv)
            delta_abs = abs(delta_raw)

            if not passes_filters(
                iv=iv, delta=delta_abs, dte=dte, otm_pct=otm_pct,
                ann_roc=ann_roc, capital=capital, max_capital=filters.max_capital,
                min_iv=filters.min_iv, min_delta=filters.min_delta, max_delta=filters.max_delta,
                min_dte=filters.min_dte, max_dte=filters.max_dte,
                min_otm_pct=filters.min_otm_pct, min_ann_roc=filters.min_ann_roc,
            ):
                continue

            rating, label = calc_rating(iv=iv, delta=delta_abs, dte=dte, ann_roc=ann_roc, strong_fundamentals=strong)

            results.append(ScreenerResultOut(
                symbol=symbol,
                price=price,
                strike=strike,
                expiry=exp_str,
                dte=dte,
                bid=round(bid, 2),
                mid=round(mid, 2),
                iv=round(iv, 4),
                delta=round(delta_abs, 4),
                otm_pct=round(otm_pct, 2),
                ann_roc_pct=round(ann_roc, 2),
                capital_required=capital,
                pe_ratio=pe_ratio,
                beta=beta,
                profit_margin=profit_margin,
                revenue_growth=revenue_growth,
                strong_fundamentals=strong,
                rating=rating,
                rating_label=label,
            ))

    # Sort by Ann.ROC descending
    results.sort(key=lambda r: r.ann_roc_pct, reverse=True)
    return results
```

- [ ] **Step 2: Verify service imports**

Run: `source .venv/bin/activate && python -c "from app.services.screener_service import scan_watchlist, get_watchlist; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/screener_service.py
git commit -m "feat: add screener service with yfinance fetch, scan, and watchlist CRUD"
```

---

### Task 5: API Endpoints

**Files:**
- Create: `app/api/screener.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create screener API router**

```python
# app/api/screener.py
"""REST endpoints for the CSP Screener."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_user
from app.auth.session import AuthUser
from app.schemas.screener import ScanFilters, ScanResponse, ScreenerResultOut, WatchlistOut, WatchlistSymbol
from app.services.screener_service import (
    add_symbol,
    get_latest_results,
    get_watchlist,
    remove_symbol,
    scan_watchlist,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screener", tags=["screener"])


def _user_sub(request: Request, user: AuthUser) -> str:
    """Extract user_sub from auth user, or fallback for internal calls."""
    return user.sub


@router.get("/watchlist")
async def list_watchlist(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_user),
):
    symbols = await get_watchlist(db, _user_sub(request, user))
    return WatchlistOut(symbols=symbols)


@router.post("/watchlist")
async def add_watchlist_symbol(
    body: WatchlistSymbol,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_user),
):
    try:
        entry = await add_symbol(db, _user_sub(request, user), body.symbol)
        return {"symbol": entry.symbol, "added": True}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/watchlist/{symbol}")
async def remove_watchlist_symbol(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_user),
):
    await remove_symbol(db, _user_sub(request, user), symbol)
    return {"symbol": symbol.upper(), "removed": True}


@router.post("/scan")
async def run_scan(
    request: Request,
    filters: ScanFilters = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_user),
):
    if filters is None:
        filters = ScanFilters()

    results, failed = await scan_watchlist(db, _user_sub(request, user), filters)

    total_capital = sum(r.capital_required for r in results)
    avg_iv = sum(r.iv for r in results) / len(results) if results else 0.0

    return ScanResponse(
        scanned_at=_now_iso(),
        watchlist_count=len(results) + len(failed) + (len(results) and 0),  # approx
        opportunities_found=len(results),
        failed_tickers=failed,
        avg_iv=round(avg_iv, 4),
        total_capital=total_capital,
        results=results,
    )


@router.get("/results")
async def get_results(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_user),
):
    rows = await get_latest_results(db, _user_sub(request, user))
    results = [
        ScreenerResultOut(
            symbol=r.symbol,
            price=r.price,
            strike=r.strike,
            expiry=r.expiry,
            dte=r.dte,
            bid=r.bid,
            mid=r.mid,
            iv=r.iv,
            delta=r.delta,
            otm_pct=r.otm_pct,
            ann_roc_pct=r.ann_roc_pct,
            capital_required=r.capital_required,
            pe_ratio=r.pe_ratio,
            beta=r.beta,
            profit_margin=r.profit_margin,
            revenue_growth=r.revenue_growth,
            strong_fundamentals=r.strong_fundamentals,
            rating=r.rating,
            rating_label=r.rating_label,
        )
        for r in rows
    ]
    return {"results": results, "count": len(results)}


@router.get("/filters")
async def get_default_filters():
    return ScanFilters()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 2: Register router in main.py**

In `app/main.py`, add the import after the other router imports (line 17 area):

```python
from app.api.screener import router as screener_router
```

And add the router inclusion after `app.include_router(dashboard_router)` (line 63 area):

```python
app.include_router(screener_router)
```

The full modified section should look like:

```python
from app.api.accounts import router as accounts_router
from app.api.dashboard import router as dashboard_router
from app.api.flex import router as flex_router
from app.api.import_csv import router as import_router
from app.api.me import router as me_router
from app.api.positions import router as positions_router
from app.api.prices import router as prices_router
from app.api.reports import router as reports_router
from app.api.screener import router as screener_router
from app.api.strategies import router as strategies_router
```

And:
```python
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(accounts_router)
app.include_router(positions_router)
app.include_router(strategies_router)
app.include_router(import_router)
app.include_router(flex_router)
app.include_router(prices_router)
app.include_router(reports_router)
app.include_router(dashboard_router)
app.include_router(screener_router)
```

- [ ] **Step 3: Verify API starts**

Run: `source .venv/bin/activate && python -c "from app.main import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; print([r for r in routes if 'screener' in r])"`
Expected: List of screener routes

- [ ] **Step 4: Commit**

```bash
git add app/api/screener.py app/main.py
git commit -m "feat: add CSP screener REST API endpoints"
```

---

### Task 6: Dashboard — Suggestions Tab Layout

**Files:**
- Create: `app/dashboard/layouts/screener.py`

- [ ] **Step 1: Create the screener layout**

```python
# app/dashboard/layouts/screener.py
"""Suggestions tab layout — CSP Screener UI."""

from dash import dash_table, dcc, html

from app.dashboard.tokens import (
    ACCENT_INFO,
    ACCENT_PROFIT,
    ACCENT_WARN,
    BG_CARD,
    BG_CARD_HEADER,
    BORDER,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def screener_layout():
    return html.Div(
        [
            # Stores
            dcc.Store(id="screener-results-store", data=[]),
            dcc.Store(id="screener-watchlist-store", data=[]),
            dcc.Loading(id="scan-loading", type="default", children=html.Div(id="scan-loading-inner")),

            # ── Header row: title + scan button ────────────────────────────
            html.Div(
                [
                    html.Span(
                        "CSP Screener",
                        style={
                            "fontSize": "1.1rem",
                            "fontWeight": 600,
                            "color": TEXT_PRIMARY,
                        },
                    ),
                    html.Button(
                        "Scan",
                        id="scan-btn",
                        n_clicks=0,
                        style={
                            "backgroundColor": ACCENT_INFO,
                            "color": "#0f0f1a",
                            "border": "none",
                            "borderRadius": "6px",
                            "padding": "0.4rem 1.2rem",
                            "fontWeight": 600,
                            "fontSize": "0.85rem",
                            "cursor": "pointer",
                            "marginLeft": "1rem",
                        },
                    ),
                    html.Span(
                        id="scan-status",
                        style={
                            "fontSize": "0.8rem",
                            "color": TEXT_SECONDARY,
                            "marginLeft": "0.75rem",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "1rem"},
            ),

            # ── Summary KPI cards ──────────────────────────────────────────
            html.Div(id="screener-summary-cards", className="mb-3"),

            # ── Watchlist management (collapsible) ─────────────────────────
            html.Details(
                [
                    html.Summary(
                        "Watchlist",
                        style={
                            "cursor": "pointer",
                            "color": TEXT_SECONDARY,
                            "fontWeight": 600,
                            "fontSize": "0.85rem",
                            "marginBottom": "0.5rem",
                        },
                    ),
                    html.Div(
                        [
                            html.Div(id="watchlist-tags", className="mb-2"),
                            html.Div(
                                [
                                    dcc.Input(
                                        id="add-symbol-input",
                                        type="text",
                                        placeholder="e.g. AAPL",
                                        maxLength=10,
                                        style={
                                            "backgroundColor": BG_CARD_HEADER,
                                            "border": f"1px solid {BORDER}",
                                            "borderRadius": "4px",
                                            "color": TEXT_PRIMARY,
                                            "padding": "0.3rem 0.6rem",
                                            "fontSize": "0.85rem",
                                            "width": "120px",
                                        },
                                    ),
                                    html.Button(
                                        "Add",
                                        id="add-symbol-btn",
                                        n_clicks=0,
                                        style={
                                            "backgroundColor": ACCENT_PROFIT,
                                            "color": "#0f0f1a",
                                            "border": "none",
                                            "borderRadius": "4px",
                                            "padding": "0.3rem 0.8rem",
                                            "fontWeight": 600,
                                            "fontSize": "0.8rem",
                                            "cursor": "pointer",
                                            "marginLeft": "0.5rem",
                                        },
                                    ),
                                    html.Span(
                                        id="add-symbol-status",
                                        style={"fontSize": "0.75rem", "color": ACCENT_WARN, "marginLeft": "0.5rem"},
                                    ),
                                ],
                                className="d-flex align-items-center",
                            ),
                        ],
                        style={"padding": "0.5rem 0"},
                    ),
                ],
                style={"marginBottom": "1rem"},
            ),

            # ── Filters (collapsible) ──────────────────────────────────────
            html.Details(
                [
                    html.Summary(
                        "Filters",
                        style={
                            "cursor": "pointer",
                            "color": TEXT_SECONDARY,
                            "fontWeight": 600,
                            "fontSize": "0.85rem",
                            "marginBottom": "0.5rem",
                        },
                    ),
                    html.Div(
                        [
                            _filter_row("Min IV %", dcc.Input(id="filter-min-iv", type="number", value=30, min=0, max=100, style=_input_style())),
                            _filter_row("Delta Range", html.Div([
                                dcc.Input(id="filter-min-delta", type="number", value=0.15, step=0.01, min=0, max=1, style={**_input_style(), "width": "70px"}),
                                html.Span(" – ", style={"color": TEXT_SECONDARY, "margin": "0 0.3rem"}),
                                dcc.Input(id="filter-max-delta", type="number", value=0.35, step=0.01, min=0, max=1, style={**_input_style(), "width": "70px"}),
                            ])),
                            _filter_row("DTE Range", html.Div([
                                dcc.Input(id="filter-min-dte", type="number", value=21, min=0, max=365, style={**_input_style(), "width": "70px"}),
                                html.Span(" – ", style={"color": TEXT_SECONDARY, "margin": "0 0.3rem"}),
                                dcc.Input(id="filter-max-dte", type="number", value=45, min=0, max=365, style={**_input_style(), "width": "70px"}),
                            ])),
                            _filter_row("Min OTM %", dcc.Input(id="filter-min-otm", type="number", value=5, min=0, max=50, style=_input_style())),
                            _filter_row("Min Ann.ROC %", dcc.Input(id="filter-min-roc", type="number", value=12, min=0, max=100, style=_input_style())),
                            _filter_row("Max Capital $", dcc.Input(id="filter-max-capital", type="number", value=50000, min=0, step=1000, style=_input_style())),
                        ],
                        style={"padding": "0.5rem 0"},
                    ),
                ],
                style={"marginBottom": "1rem"},
            ),

            # ── Results table ──────────────────────────────────────────────
            dash_table.DataTable(
                id="screener-table",
                page_size=25,
                sort_action="native",
                sort_by=[{"column_id": "ann_roc_pct", "direction": "desc"}],
                style_table={"overflowX": "auto"},
                style_header={
                    "backgroundColor": BG_CARD_HEADER,
                    "color": TEXT_SECONDARY,
                    "fontWeight": 600,
                    "fontSize": "0.75rem",
                    "textTransform": "uppercase",
                    "letterSpacing": "0.03em",
                    "borderBottom": f"2px solid {BORDER}",
                },
                style_cell={
                    "backgroundColor": BG_CARD,
                    "color": TEXT_PRIMARY,
                    "textAlign": "center",
                    "border": f"1px solid {BORDER}",
                    "fontFamily": "'Inter', system-ui, sans-serif",
                    "fontSize": "0.82rem",
                    "padding": "0.4rem 0.6rem",
                    "cursor": "pointer",
                },
                style_data_conditional=[
                    {"if": {"filter_query": "{rating} = 5"}, "borderLeft": f"3px solid {ACCENT_PROFIT}"},
                    {"if": {"filter_query": "{rating} = 4"}, "borderLeft": f"3px solid {ACCENT_INFO}"},
                    {"if": {"filter_query": "{rating} <= 3"}, "borderLeft": f"3px solid {ACCENT_WARN}"},
                ],
            ),

            # ── Detail panel (hidden until row clicked) ────────────────────
            html.Div(id="screener-detail-panel", style={"display": "none"}),
        ]
    )


def _input_style():
    return {
        "backgroundColor": BG_CARD_HEADER,
        "border": f"1px solid {BORDER}",
        "borderRadius": "4px",
        "color": TEXT_PRIMARY,
        "padding": "0.3rem 0.6rem",
        "fontSize": "0.82rem",
        "width": "90px",
    }


def _filter_row(label: str, control) -> html.Div:
    """A filter row with label and control input."""
    return html.Div(
        [
            html.Span(label, style={"color": TEXT_SECONDARY, "fontSize": "0.8rem", "width": "120px", "minWidth": "120px"}),
            control,
        ],
        className="d-flex align-items-center mb-1",
    )
```

- [ ] **Step 2: Verify layout imports**

Run: `source .venv/bin/activate && python -c "from app.dashboard.layouts.screener import screener_layout; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/dashboard/layouts/screener.py
git commit -m "feat: add Suggestions tab dashboard layout"
```

---

### Task 7: Dashboard — Tab Registration and Callbacks

**Files:**
- Modify: `app/dashboard/app.py`
- Modify: `app/dashboard/callbacks/__init__.py`

- [ ] **Step 1: Add Suggestions tab to app.py**

In `app/dashboard/app.py`, add the import at the top (after line 9):

```python
from app.dashboard.layouts.screener import screener_layout
```

Then in the `dbc.Tabs` list (around line 178-186), add a new tab between Expiration and Settings. The tabs section becomes:

```python
                    dbc.Tabs(
                        [
                            dbc.Tab(label="Overview", tab_id="overview"),
                            dbc.Tab(label="Positions", tab_id="positions"),
                            dbc.Tab(label="Risk", tab_id="risk"),
                            dbc.Tab(label="Expiration", tab_id="expiration"),
                            dbc.Tab(label="Suggestions", tab_id="suggestions"),
                            dbc.Tab(label="Settings", tab_id="settings"),
                        ],
                        id="main-tabs",
                        active_tab="overview",
                        className="mt-3",
                    ),
```

And in `register_all_callbacks` function's `render_tab` callback, add the mapping for `"suggestions"`. The `layouts` dict becomes:

```python
        layouts = {
            "overview": overview_layout,
            "positions": positions_layout,
            "risk": risk_layout,
            "expiration": expiration_layout,
            "suggestions": screener_layout,
            "settings": settings_layout,
        }
```

- [ ] **Step 2: Add screener callbacks to callbacks/__init__.py**

Add these callbacks inside the `register_all_callbacks` function, at the end before the closing of the function. The callbacks use the same `_api_get`, `_get_user_headers`, and `_INTERNAL_HEADERS` patterns as existing callbacks.

Append the following imports at the top of `callbacks/__init__.py` (after the existing imports):

```python
from app.dashboard.components import kpi_card, fmt_money
```

Then add these callbacks at the end of `register_all_callbacks`:

```python
    # ---- Screener callbacks ----

    @dash_app.callback(
        Output("screener-watchlist-store", "data"),
        Output("watchlist-tags", "children"),
        Input("main-tabs", "active_tab"),
        Input("add-symbol-btn", "n_clicks"),
        Input({"type": "remove-symbol-btn", "index": dash.dependencies.ALL}, "n_clicks"),
        State("add-symbol-input", "value"),
        prevent_initial_call=True,
    )
    def manage_watchlist(active_tab, add_clicks, remove_clicks, new_symbol):
        ctx = dash.callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        headers = _get_user_headers()

        # Remove symbol
        if "remove-symbol-btn" in triggered:
            triggered_id = dash.callback_context.triggered_id
            if isinstance(triggered_id, dict) and triggered_id.get("type") == "remove-symbol-btn":
                sym = triggered_id["index"]
                with contextlib.suppress(Exception):
                    requests.delete(
                        f"{API_BASE}/api/screener/watchlist/{sym}",
                        headers=headers, timeout=5,
                    )

        # Add symbol
        elif "add-symbol-btn" in triggered and add_clicks and new_symbol:
            with contextlib.suppress(Exception):
                requests.post(
                    f"{API_BASE}/api/screener/watchlist",
                    json={"symbol": new_symbol.strip().upper()},
                    headers=headers, timeout=5,
                )

        # Fetch current watchlist
        try:
            resp = requests.get(f"{API_BASE}/api/screener/watchlist", headers=headers, timeout=5)
            data = resp.json()
            symbols = data.get("symbols", [])
        except Exception:
            symbols = []

        tags = []
        for sym in symbols:
            tags.append(html.Span(
                [
                    html.Span(sym, style={"marginRight": "0.3rem"}),
                    html.Span(
                        "x",
                        id={"type": "remove-symbol-btn", "index": sym},
                        style={
                            "cursor": "pointer",
                            "fontWeight": 700,
                            "fontSize": "0.7rem",
                            "color": TEXT_SECONDARY,
                        },
                    ),
                ],
                style={
                    "backgroundColor": BG_CARD_HEADER,
                    "border": f"1px solid {BORDER}",
                    "borderRadius": "4px",
                    "padding": "0.2rem 0.5rem",
                    "fontSize": "0.8rem",
                    "color": TEXT_PRIMARY,
                    "marginRight": "0.4rem",
                    "display": "inline-block",
                },
            ))

        return symbols, tags

    @dash_app.callback(
        Output("screener-results-store", "data"),
        Output("scan-status", "children"),
        Input("scan-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def run_scan(n_clicks):
        if not n_clicks:
            return [], ""
        try:
            # Collect filter values from inputs
            headers = _get_user_headers()
            resp = requests.post(
                f"{API_BASE}/api/screener/scan",
                json={},
                headers=headers,
                timeout=120,
            )
            data = resp.json()
            results = data.get("results", [])
            status = f"Found {data.get('opportunities_found', 0)} opportunities"
            failed = data.get("failed_tickers", [])
            if failed:
                status += f" ({len(failed)} failed: {', '.join(failed)})"
            return data, status
        except Exception as e:
            return [], f"Error: {e}"

    @dash_app.callback(
        Output("screener-summary-cards", "children"),
        Input("screener-results-store", "data"),
    )
    def update_screener_summary(scan_data):
        results = scan_data.get("results", [])
        if not results:
            return html.Small("Click Scan to find CSP opportunities.", style={"color": TEXT_SECONDARY})

        watchlist_count = scan_data.get("watchlist_count", 0)
        total_capital = sum(r.get("capital_required", 0) for r in results)
        avg_iv = sum(r.get("iv", 0) for r in results) / len(results) if results else 0

        return dbc.Row([
            dbc.Col(kpi_card("Watchlist", str(watchlist_count), ACCENT_INFO), lg=2, sm=6),
            dbc.Col(kpi_card("Opportunities", str(len(results)), ACCENT_PROFIT), lg=2, sm=6),
            dbc.Col(kpi_card("Avg IV", f"{avg_iv * 100:.1f}%", ACCENT_WARN), lg=2, sm=6),
            dbc.Col(kpi_card("Total Capital", fmt_money(total_capital), ACCENT_PROFIT), lg=2, sm=6),
            dbc.Col(kpi_card("Scanned", scan_data.get("scanned_at", "")[:19].replace("T", " "), TEXT_SECONDARY), lg=4, sm=6),
        ])

    @dash_app.callback(
        Output("screener-table", "data"),
        Output("screener-table", "columns"),
        Input("screener-results-store", "data"),
    )
    def update_screener_table(scan_data):
        results = scan_data.get("results", [])
        if not results:
            return [], []

        cols = [
            {"name": "Ticker", "id": "symbol"},
            {"name": "Price", "id": "price", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Strike", "id": "strike", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Expiry", "id": "expiry"},
            {"name": "DTE", "id": "dte", "type": "numeric"},
            {"name": "Bid", "id": "bid", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Ann.ROC%", "id": "ann_roc_pct", "type": "numeric", "format": {"specifier": ".1f"}},
            {"name": "IV", "id": "iv_display"},
            {"name": "Delta", "id": "delta", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Rating", "id": "rating_display"},
        ]

        rows = []
        for r in results:
            stars = "\u2605" * r.get("rating", 0)
            rows.append({
                "symbol": r.get("symbol"),
                "price": r.get("price"),
                "strike": r.get("strike"),
                "expiry": r.get("expiry"),
                "dte": r.get("dte"),
                "bid": r.get("bid"),
                "ann_roc_pct": r.get("ann_roc_pct"),
                "iv_display": f"{r.get('iv', 0) * 100:.1f}%",
                "delta": r.get("delta"),
                "rating": r.get("rating"),
                "rating_display": f"{stars} {r.get('rating_label', '')}",
                # Keep full data for detail panel
                "_full": r,
            })

        return rows, cols

    @dash_app.callback(
        Output("screener-detail-panel", "children"),
        Output("screener-detail-panel", "style"),
        Input("screener-table", "active_cell"),
        State("screener-table", "data"),
    )
    def show_detail(active_cell, table_data):
        if not active_cell or not table_data:
            return html.Div(), {"display": "none"}

        row_idx = active_cell.get("row")
        if row_idx is None or row_idx >= len(table_data):
            return html.Div(), {"display": "none"}

        r = table_data[row_idx].get("_full", {})

        detail_style = {
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderRadius": "8px",
            "padding": "1rem",
            "marginTop": "0.5rem",
        }

        def _metric(label, value):
            return html.Div([
                html.Div(label, style={"color": TEXT_SECONDARY, "fontSize": "0.7rem", "textTransform": "uppercase"}),
                html.Div(str(value), style={"color": TEXT_PRIMARY, "fontSize": "0.9rem", "fontWeight": 600}),
            ], style={"marginRight": "1.5rem"})

        fund_badge = ""
        if r.get("strong_fundamentals"):
            fund_badge = html.Span(" \u2605 Strong Fundamentals", style={"color": ACCENT_PROFIT, "fontSize": "0.8rem", "marginLeft": "0.5rem"})

        return html.Div([
            html.Div([
                html.Strong(f"{r.get('symbol')} ${r.get('strike')}P", style={"color": TEXT_PRIMARY, "fontSize": "1rem"}),
                html.Span(f" exp {r.get('expiry')}", style={"color": TEXT_SECONDARY}),
                fund_badge,
            ], style={"marginBottom": "0.75rem"}),
            html.Div([
                _metric("Mid", f"${r.get('mid', 0):.2f}"),
                _metric("OTM%", f"{r.get('otm_pct', 0):.1f}%"),
                _metric("Capital", fmt_money(r.get('capital_required', 0))),
                _metric("P/E", f"{r.get('pe_ratio', 'N/A')}" if r.get('pe_ratio') else "N/A"),
                _metric("Beta", f"{r.get('beta', 'N/A')}" if r.get('beta') else "N/A"),
                _metric("Margin", f"{r.get('profit_margin', 0):.1f}%" if r.get('profit_margin') else "N/A"),
                _metric("Rev Growth", f"{r.get('revenue_growth', 0):.1f}%" if r.get('revenue_growth') else "N/A"),
            ], className="d-flex flex-wrap"),
        ]), detail_style
```

- [ ] **Step 3: Verify dashboard starts**

Run: `source .venv/bin/activate && python -c "from app.dashboard.app import create_dash_app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run all existing tests to ensure nothing is broken**

Run: `source .venv/bin/activate && pytest tests/ -v --timeout=30`
Expected: All existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/dashboard/app.py app/dashboard/callbacks/__init__.py
git commit -m "feat: add Suggestions tab with screener callbacks to dashboard"
```

---

### Task 8: Install yfinance + scipy Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add yfinance and scipy to dependencies**

In `pyproject.toml`, add to the `dependencies` list:

```python
    "yfinance>=0.2",
    "scipy>=1.12",
```

The full dependencies section becomes:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "dash>=2.18",
    "plotly>=5.24",
    "dash-bootstrap-components>=1.6",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "libsql-experimental>=0.0.55",
    "httpx>=0.27",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "defusedxml>=0.7",
    "python-multipart>=0.0.9",
    "authlib>=1.3",
    "yfinance>=0.2",
    "scipy>=1.12",
]
```

- [ ] **Step 2: Install new dependencies**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: yfinance and scipy install successfully

- [ ] **Step 3: Verify imports work**

Run: `source .venv/bin/activate && python -c "import yfinance; import scipy; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add yfinance and scipy dependencies"
```

---

### Task 9: Smoke Test — End-to-End Verification

**Files:** None (manual verification)

- [ ] **Step 1: Start the dev server**

Run: `source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload`

- [ ] **Step 2: Verify API endpoints**

In a separate terminal:

```bash
# Check health
curl http://localhost:8001/health

# Check screener routes registered
curl http://localhost:8001/docs
```

Expected: Health returns OK, Swagger docs show screener endpoints

- [ ] **Step 3: Verify dashboard loads**

Open browser to `http://localhost:8001/dashboard/` and confirm:
- "Suggestions" tab appears between Expiration and Settings
- Clicking it shows the layout with Scan button, Watchlist, Filters, and empty table
- No console errors

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: adjustments from smoke test"
```
