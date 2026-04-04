# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IBKR Options Analyzer — a Python web app for tracking and analyzing non-expired open option positions across multiple Interactive Brokers accounts. Provides per-account and consolidated cross-account views for option selling strategies (especially short puts) with risk analysis, delivered as a cloud-deployable web dashboard.

## Tech Stack

- **Python 3.12+** with FastAPI backend
- **Dash + Plotly + dash-bootstrap-components** for dashboard UI
- **SQLite via SQLAlchemy** (async with aiosqlite)
- **httpx** for async HTTP, **defusedxml** for safe XML parsing
- **Pydantic v2 + pydantic-settings** for validation/config
- **pytest + pytest-asyncio** for testing, **ruff** for linting
- **Docker** (multi-stage) deployed to Railway or Render

## Commands

```bash
# Create venv & install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run dev server (port 8001 to avoid conflict with port 8000)
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
# Lint
ruff check .
ruff format .

# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_option_symbol.py

# Run specific test by name
pytest tests/unit/test_option_symbol.py::test_parse_compact_symbol -v

# Docker build & run
docker build -t ibkr-options-analyzer .
docker run -p 8000:8000 ibkr-options-analyzer

# Docker compose
docker compose up --build
```

## Architecture

```
app/
├── main.py              # FastAPI app + Dash mounted at /dashboard/ via WSGIMiddleware
├── config.py            # Pydantic Settings (env > .env > defaults)
├── database.py          # Async SQLAlchemy engine + session (aiosqlite)
├── models/              # SQLAlchemy ORM: accounts, trades, open_options, detected_strategies, strategy_legs, metadata
├── schemas/             # Pydantic: position, strategy, risk, option, flex
├── parsers/             # Pure functions — option symbol parsing + CSV parsing (no I/O)
├── analysis/            # Pure functions — strategy detection + risk calculation (no I/O)
├── services/            # Orchestration layer (DB + logic + external I/O)
│   ├── account_service.py
│   ├── position_service.py
│   ├── strategy_service.py
│   ├── import_service.py
│   ├── flex_service.py
│   ├── price_service.py
│   └── report_service.py
├── api/                 # REST endpoints (deps.py for DB session dependency)
│   ├── accounts.py, positions.py, strategies.py
│   ├── import_csv.py, flex.py, prices.py
│   ├── reports.py, dashboard.py
├── dashboard/           # Dash frontend (v4, mounted via WSGIMiddleware)
│   ├── app.py           # Dash app factory, WSGI mount
│   ├── layouts/         # main, positions, strategies, risk, expiration, import, settings
│   └── callbacks/       # All callbacks in __init__.py, calls API via requests
└── utils/               # http_client (retry wrapper), xml_parser (safe Flex response parsing)
```

### Key Architectural Patterns

- **Layered separation:** `parsers/` and `analysis/` are pure functions with no I/O — all side effects live in `services/`. This makes core business logic independently testable.
- **Multi-account isolation:** All positions/strategies are tagged with `account_id`. API endpoints accept optional `account_id` query param — omitting it returns consolidated cross-account views.
- **Dash + FastAPI single process:** Dash v4 standalone Flask app mounted via `starlette.middleware.wsgi.WSGIMiddleware` at `/dashboard`. API at `/api/...`, Swagger at `/docs`.
- **JSON inf handling:** `float('inf')` max_loss values are serialized as `"unlimited"` in API responses (JSON can't represent infinity).
- **SQLite constraints:** Single worker only (concurrent write limitation). DB file at configurable path, persisted via mounted volume in production.

### IBKR Integration

- **Flex Web Service API v3:** SendRequest → poll GetStatement → parse CSV/XML. Each account has its own token + query_id. Downloads run sequentially per account, partial success supported.
- **Option symbol formats:** Two IBKR formats parsed in `parsers/option_symbol.py` (space-padded 8-digit strike and compact decimal strike).
- **Stock prices:** Yahoo Finance (primary, no key) + Alpha Vantage (fallback, requires key via `ALPHAVANTAGE_API_KEY`).

### Data Flow

1. Data arrives via CSV upload, file discovery, or Flex API download
2. CSV parsed by `parsers/csv_parser.py` with option symbol parsing from `parsers/option_symbol.py`
3. Parsed records stored in SQLite via service layer
4. `analysis/strategy_detector.py` groups positions into strategies (naked puts/calls, spreads, iron condors, straddles, strangles)
5. `analysis/risk_calculator.py` computes per-strategy risk metrics (breakeven, max profit/loss, risk level)
6. Dashboard and REST API expose both per-account and consolidated views

## Configuration

Environment variables (prefix `IBKR_`): `IBKR_DB_PATH`, `IBKR_HTTP_TIMEOUT`, `IBKR_HTTP_MAX_RETRIES`, `IBKR_HTTP_RETRY_DELAY_MS`, `IBKR_FLEX_POLL_INTERVAL`, `IBKR_FLEX_MAX_POLL_DURATION`, `IBKR_LOG_LEVEL`, `ALPHAVANTAGE_API_KEY`. See `.env.example` for defaults.
