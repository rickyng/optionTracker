# CSP Screener — Design Spec

**Date:** 2026-04-10
**Status:** Approved

## Overview

A professional-grade Cash-Secured Put screener integrated into the IBKR Options Analyzer web dashboard as a new "Suggestions" tab. Uses free data sources (yfinance, scipy) to scan a user-managed watchlist, evaluate put-selling opportunities, and present ranked results with a composite rating system.

## Architecture

Follows existing layered patterns: models → analysis (pure) → services (I/O) → API → dashboard.

### Data Source

- **yfinance** for options chains (strikes, premiums, IV, expirations), underlying prices, and fundamentals
- **scipy.stats.norm** for Black-Scholes delta calculation
- IV sourced directly from yfinance's `impliedVolatility` field on ATM puts (no historical lookback)

## Section 1: Data Models

New file: `app/models/screener.py`

### ScreenerWatchlist (per-user)

| Column | Type | Description |
|--------|------|-------------|
| id | Integer PK | Auto-increment |
| user_sub | String | Links to user (from auth) |
| symbol | String | Ticker symbol (e.g. "NVDA") |
| created_at | DateTime | When added |
| updated_at | DateTime | Last modified |

Unique constraint on `(user_sub, symbol)`.

### ScreenerResult (cached scan results)

| Column | Type | Description |
|--------|------|-------------|
| id | Integer PK | Auto-increment |
| user_sub | String | Links to user |
| symbol | String | Ticker |
| price | Float | Current underlying price |
| strike | Float | Put strike |
| expiry | String | Expiration date (YYYY-MM-DD) |
| dte | Integer | Days to expiration |
| bid | Float | Bid premium |
| mid | Float | Mid price |
| iv | Float | Implied volatility (decimal, e.g. 0.45) |
| delta | Float | Black-Scholes delta (absolute value) |
| otm_pct | Float | OTM distance % |
| ann_roc_pct | Float | Annualized return on capital |
| capital_required | Float | Strike * 100 |
| pe_ratio | Float | P/E ratio |
| beta | Float | Beta |
| profit_margin | Float | Profit margin % |
| revenue_growth | Float | Revenue growth YoY |
| strong_fundamentals | Boolean | Meets fundamentals criteria |
| rating | Integer | Composite score 1-5 |
| rating_label | String | "STRONG" / "GOOD" / "OK" |
| scanned_at | DateTime | When this result was fetched |

Composite index on `(user_sub, scanned_at)`. Old results deleted on each new scan (keep only latest scan per user).

## Section 2: Analysis Layer

New file: `app/analysis/option_greeks.py` — pure functions, no I/O.

### `black_scholes_put_delta(S, K, T, r, sigma) -> float`

Standard Black-Scholes put delta using `scipy.stats.norm`. Parameters: S=spot, K=strike, T=DTE/365, r=risk-free rate (default 5.0%), sigma=IV. Returns negative delta (e.g., -0.25); callers display absolute value.

### `calc_otm_pct(price, strike) -> float`

`(price - strike) / price * 100`. Returns positive for OTM puts.

### `calc_ann_roc(premium, strike, dte) -> float`

`(premium / strike) / dte * 365 * 100`.

### `calc_rating(iv, delta, dte, ann_roc, strong_fundamentals) -> tuple[int, str]`

Scoring:

| Condition | Points |
|-----------|--------|
| IV >= 60% | +2 |
| IV 30-60% | +1 |
| IV < 30% | -1 |
| Delta 0.20-0.30 | +2 |
| Delta 0.15-0.20 or 0.30-0.35 | +0 |
| Delta outside 0.15-0.35 | -1 |
| DTE 30-45 | +2 |
| DTE 21-30 or 45+ | +0 |
| Ann.ROC >= 20% | +2 |
| Ann.ROC 12-20% | +1 |
| Strong fundamentals | +1 |

Mapping: 5+ = ★★★★★ STRONG, 3-4 = ★★★★ GOOD, 1-2 = ★★★ OK.

### `passes_filters(iv, delta, dte, otm_pct, ann_roc, capital, max_capital) -> bool`

Applies all configurable thresholds.

### `is_strong_fundamentals(pe_ratio, profit_margin, beta) -> bool`

True when: P/E > 0, profit margin > 10%, beta < 1.5.

## Section 3: Service Layer

New file: `app/services/screener_service.py`.

### Dependencies

- `app/services/price_service.py` — reuses Yahoo Finance fetch for underlying prices
- `app/utils/http_client.py` — reuses retry wrapper
- `app/analysis/option_greeks.py` — pure calculations

### `scan_watchlist(user_sub, filters: ScanFilters) -> list[ScreenerResult]`

1. Load user's watchlist from DB
2. Parallel fetch per ticker (asyncio.gather with semaphore, max 3 concurrent):
   - Underlying price via `price_service.fetch_price()`
   - Options chain via yfinance: `Ticker.options` → `Ticker.option_chain(expiry)` for next 2-3 expirations in 21-45 DTE window
   - Fundamentals via `Ticker.info` dict (P/E, beta, profit margin, revenue growth)
3. For each put contract: get IV from yfinance `impliedVolatility`, compute delta/OTM%/ROC/rating, apply filters
4. Delete old scan results for user, store passing results to DB
5. Return sorted by Ann.ROC desc

### ScanFilters (Pydantic model in `app/schemas/screener.py`)

```python
min_iv: float = 0.30
min_delta: float = -0.35
max_delta: float = -0.15
min_dte: int = 21
max_dte: int = 45
min_otm_pct: float = 5.0
min_ann_roc: float = 12.0
max_capital: float = 50000.0
max_beta: float = 2.5
```

### Watchlist CRUD

- `get_watchlist(user_sub) -> list[str]`
- `add_symbol(user_sub, symbol) -> ScreenerWatchlist`
- `remove_symbol(user_sub, symbol) -> None`
- `get_latest_results(user_sub) -> list[ScreenerResult]`

### Error handling

Individual ticker failures logged and skipped (partial success, same as flex_service). Scan returns whatever resolved with failure summary.

## Section 4: API Endpoints

New file: `app/api/screener.py`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/screener/watchlist` | Get user's watchlist symbols |
| POST | `/api/screener/watchlist` | Add symbol `{ "symbol": "NVDA" }` |
| DELETE | `/api/screener/watchlist/{symbol}` | Remove symbol |
| POST | `/api/screener/scan` | Trigger scan with optional filter overrides |
| GET | `/api/screener/results` | Cached results; query: `sort_by`, `sort_dir` |
| GET | `/api/screener/filters` | Current default filter values |

### Scan response

```json
{
  "scanned_at": "2026-04-10T14:30:00Z",
  "watchlist_count": 20,
  "opportunities_found": 35,
  "failed_tickers": ["U"],
  "avg_iv": 0.42,
  "total_capital": 875000,
  "results": [...]
}
```

All endpoints require auth via `X-Internal-API-Key` or session cookie.

## Section 5: Dashboard — Suggestion Tab

New file: `app/dashboard/layouts/screener.py` + callbacks in `callbacks/__init__.py`.

### Tab registration

`dbc.Tab(label="Suggestions", tab_id="suggestions")` added between Expiration and Settings.

### Layout

**Summary header** — 5 KPI cards (Watchlist Count, Opportunities, Avg IV, Total Capital, Last Scanned) + "Scan" button with loading spinner.

**Filter controls** (collapsible panel):
- IV threshold slider (10-100%, default 30%)
- Delta range dual slider (0.10-0.50, default 0.15-0.35)
- DTE range dual slider (14-90, default 21-45)
- Min OTM% input (default 5%)
- Min Ann.ROC input (default 12%)
- Max Capital input (default $50,000)
- "Apply Filters" button — re-filters cached results client-side

**Results table + detail panel:**

Compact table: `Ticker | Price | Strike | Expiry | DTE | Bid | Ann.ROC% | IV | Delta | Rating`

Click row → expand detail panel with: Mid price, OTM%, Capital, P/E, Beta, Profit Margin, Revenue Growth, fundamentals ★ badge, rating stars + label.

### Callbacks

| Callback | Trigger | Action |
|----------|---------|--------|
| `scan_results` | Scan button click | POST scan, load results into dcc.Store |
| `update_summary_cards` | Results store change | Update KPI cards |
| `update_results_table` | Results store + filter state | Populate compact table |
| `show_detail_panel` | Table row click | Expand detail for selected row |
| `load_watchlist` | Tab activation | GET watchlist |
| `add_to_watchlist` | Add symbol button | POST to watchlist |
| `remove_from_watchlist` | Remove button per symbol | DELETE from watchlist |

### Watchlist management

Collapsible panel within Suggestions tab. Simple symbol list with add/remove. Default watchlist seeded on first use: ADBE, AMZN, AVGO, BRK-B, GOOG, META, MSFT, NFLX, NVDA, ORCL, PEP, PLTR, PYPL, SAP, TSLA, TSM, U, UNH, V.

## Files to Create/Modify

| File | Action |
|------|--------|
| `app/models/screener.py` | Create — SQLAlchemy models |
| `app/models/__init__.py` | Modify — import new models |
| `app/schemas/screener.py` | Create — Pydantic schemas + ScanFilters |
| `app/analysis/option_greeks.py` | Create — pure calculation functions |
| `app/services/screener_service.py` | Create — scan orchestration + CRUD |
| `app/api/screener.py` | Create — REST endpoints |
| `app/api/deps.py` | Modify — add screener session dependency if needed |
| `app/main.py` | Modify — register screener router |
| `app/database.py` | Modify — ensure new tables created on startup |
| `app/dashboard/app.py` | Modify — add Suggestions tab |
| `app/dashboard/layouts/screener.py` | Create — Suggestion tab layout |
| `app/dashboard/callbacks/__init__.py` | Modify — add screener callbacks |
| `tests/unit/test_option_greeks.py` | Create — unit tests for pure functions |
