"""Consolidated Yahoo Finance data layer.

Single entry point for all yfinance calls. Makes one `yf.Ticker(symbol).info`
call per symbol, extracts price + earnings + fundamentals, and upserts into
existing market_prices and earnings_dates tables.

Same-day validity: skips symbols already fetched today.
Sequential fetches with 2s delay to avoid rate limiting.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, date, datetime

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_fx_rate
from app.models.earnings_date import EarningsDate
from app.models.market_price import MarketPrice
from app.services.price_service import _yahoo_lookup_symbol
from app.utils.cache import dashboard_summary_cache

logger = logging.getLogger(__name__)

_DELAY_BETWEEN_FETCHES = 2.0  # seconds between yfinance calls


def _is_fresh_today(updated_at_str: str | None) -> bool:
    """Check if a timestamp is from today (same calendar day in UTC)."""
    if not updated_at_str:
        return False
    try:
        ts = datetime.fromisoformat(updated_at_str)
        return ts.date() >= datetime.now(UTC).date()
    except (ValueError, TypeError):
        return False


async def refresh_if_stale(db: AsyncSession, symbols: list[str]) -> dict[str, dict]:
    """Fetch yfinance data for stale symbols. One call per symbol.

    Returns dict of symbol → {price, earnings_date, pe_ratio, beta, ...}
    for symbols that were actually fetched.
    """
    if not symbols:
        return {}

    # Determine which symbols need fresh data
    stale_symbols = await _get_stale_symbols(db, symbols)

    if not stale_symbols:
        logger.info("All %d symbols fresh, skipping yfinance fetch", len(symbols))
        return {}

    logger.info("Fetching yfinance data for %d/%d stale symbols", len(stale_symbols), len(symbols))

    results: dict[str, dict] = {}

    for i, symbol in enumerate(stale_symbols):
        if i > 0:
            await asyncio.sleep(_DELAY_BETWEEN_FETCHES)

        try:
            data = await _fetch_ticker_info(symbol)
            if data:
                results[symbol] = data
                _upsert_price(db, symbol, data)
                _upsert_earnings(db, symbol, data)
        except Exception as e:
            logger.warning("yfinance fetch failed for %s: %s", symbol, e)

    if results:
        await db.commit()
        dashboard_summary_cache.invalidate()

    logger.info(
        "yfinance refresh complete: %d/%d succeeded",
        len(results),
        len(stale_symbols),
    )

    return results


async def _get_stale_symbols(db: AsyncSession, symbols: list[str]) -> list[str]:
    """Return symbols that don't have fresh (today) data in market_prices."""
    result = await db.execute(select(MarketPrice).where(MarketPrice.symbol.in_(symbols)))
    rows = {row.symbol: row for row in result.scalars().all()}

    stale: list[str] = []
    for sym in symbols:
        row = rows.get(sym)
        if not row or not _is_fresh_today(row.updated_at):
            stale.append(sym)

    return stale


async def _fetch_ticker_info(symbol: str) -> dict | None:
    """One yfinance call — extracts price, earnings, fundamentals."""
    lookup = _yahoo_lookup_symbol(symbol)
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, _get_ticker_info, lookup)

    if not info:
        return None

    # Extract price
    price = info.get("currentPrice") or info.get("regularMarketPrice")

    # Extract earnings date
    earnings_date = None
    ts = info.get("earningsTimestamp")
    if ts:
        with contextlib.suppress(ValueError, OSError):
            earnings_date = date.fromtimestamp(ts).isoformat()

    return {
        "price": price,
        "earnings_date": earnings_date,
        "pe_ratio": info.get("trailingPE"),
        "beta": info.get("beta"),
        "profit_margin": info.get("profitMargins"),
        "revenue_growth": info.get("revenueGrowth"),
    }


def _get_ticker_info(lookup: str) -> dict | None:
    """Synchronous: fetch ticker.info from yfinance."""
    try:
        ticker = yf.Ticker(lookup)
        info = ticker.info
        if not info:
            return None
        return info
    except Exception:
        return None


def _upsert_price(db: AsyncSession, symbol: str, data: dict) -> None:
    """Upsert market price (converted to USD)."""
    price = data.get("price")
    if price is None:
        return

    rate = get_fx_rate(symbol)
    usd_price = price * rate
    now = datetime.now(UTC).isoformat()

    row_result = db.execute(select(MarketPrice).where(MarketPrice.symbol == symbol))
    row = row_result.scalar_one_or_none()

    if row:
        row.price = usd_price
        row.updated_at = now
    else:
        db.add(MarketPrice(symbol=symbol, price=usd_price, updated_at=now))


def _upsert_earnings(db: AsyncSession, symbol: str, data: dict) -> None:
    """Upsert earnings date."""
    earnings_date = data.get("earnings_date")
    if earnings_date is None:
        return

    now = datetime.now(UTC).isoformat()

    row_result = db.execute(select(EarningsDate).where(EarningsDate.symbol == symbol))
    row = row_result.scalar_one_or_none()

    if row:
        row.earnings_date = earnings_date
        row.updated_at = now
    else:
        db.add(EarningsDate(symbol=symbol, earnings_date=earnings_date, updated_at=now))


async def refresh_all_underlyings(
    db: AsyncSession,
    user_account_ids: list[int] | None = None,
) -> dict[str, dict]:
    """Refresh yfinance data for all underlyings in current positions."""
    from app.models.open_option import OpenOption

    query = select(OpenOption.underlying).distinct()
    if user_account_ids is not None:
        query = query.where(OpenOption.account_id.in_(user_account_ids))

    result = await db.execute(query)
    symbols = sorted([row[0] for row in result.all()])

    return await refresh_if_stale(db, symbols)
