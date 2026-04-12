"""Service for managing cached earnings dates in the database.

Earnings dates are fetched from Yahoo Finance via yfinance and stored in
the earnings_dates table. Dashboard reads from DB (instant) to display
earnings context next to option positions.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.earnings_date import EarningsDate
from app.utils.cache import dashboard_summary_cache

logger = logging.getLogger(__name__)

_STALE_DAYS = 7
_SEMAPHORE = asyncio.Semaphore(1)
_DELAY_BETWEEN_FETCHES = 2.0  # seconds between yfinance calls to avoid rate limiting


async def get_earnings_dates(db: AsyncSession, symbols: list[str]) -> dict[str, str | None]:
    """Get cached earnings dates from DB. Stale entries (>7 days) return None."""
    if not symbols:
        return {}

    result = await db.execute(select(EarningsDate).where(EarningsDate.symbol.in_(symbols)))
    rows = result.scalars().all()

    cutoff = datetime.now(UTC) - timedelta(days=_STALE_DAYS)

    dates: dict[str, str | None] = {sym: None for sym in symbols}
    for row in rows:
        try:
            if datetime.fromisoformat(row.updated_at) >= cutoff:
                dates[row.symbol] = row.earnings_date
        except (ValueError, TypeError):
            pass

    return dates


async def refresh_earnings_dates(
    db: AsyncSession, symbols: list[str]
) -> dict[str, str | None]:
    """Fetch earnings dates via yfinance, upsert into DB, return results.

    Skips symbols with fresh cache (< 7 days old).
    """
    if not symbols:
        return {}

    # Check which symbols already have fresh cache
    result = await db.execute(select(EarningsDate).where(EarningsDate.symbol.in_(symbols)))
    existing_map = {row.symbol: row for row in result.scalars().all()}

    cutoff = datetime.now(UTC) - timedelta(days=_STALE_DAYS)

    stale_symbols: list[str] = []
    dates: dict[str, str | None] = {}

    for sym in symbols:
        row = existing_map.get(sym)
        if row and row.updated_at:
            try:
                if datetime.fromisoformat(row.updated_at) >= cutoff:
                    dates[sym] = row.earnings_date
                    continue
            except (ValueError, TypeError):
                pass
        stale_symbols.append(sym)

    if not stale_symbols:
        logger.info("All %d earnings dates fresh, skipping fetch", len(symbols))
        return dates

    logger.info("Refreshing earnings dates for %d/%d symbols (rest cached)", len(stale_symbols), len(symbols))
    fetched = await fetch_earnings_batch(stale_symbols)

    now = datetime.now(UTC).isoformat()

    for symbol, earnings_date in fetched.items():
        row = existing_map.get(symbol)
        if row:
            row.earnings_date = earnings_date
            row.updated_at = now
        else:
            db.add(EarningsDate(symbol=symbol, earnings_date=earnings_date, updated_at=now))

    await db.commit()
    dashboard_summary_cache.invalidate()

    dates.update(fetched)
    found = sum(1 for v in fetched.values() if v is not None)
    logger.info("Earnings refresh complete: %d found, %d missing", found, len(stale_symbols) - found)

    return dates


async def refresh_all_earnings_dates(
    db: AsyncSession,
    user_account_ids: list[int] | None = None,
) -> dict[str, str | None]:
    """Refresh earnings dates for all underlyings in current positions."""
    from app.models.open_option import OpenOption

    query = select(OpenOption.underlying).distinct()
    if user_account_ids is not None:
        query = query.where(OpenOption.account_id.in_(user_account_ids))

    result = await db.execute(query)
    symbols = [row[0] for row in result.all()]

    return await refresh_earnings_dates(db, symbols)


async def fetch_earnings_batch(symbols: list[str]) -> dict[str, str | None]:
    """Fetch upcoming earnings dates for multiple symbols via yfinance.

    Runs sequentially with delays to avoid rate limiting.
    """
    if not symbols:
        return {}

    loop = asyncio.get_running_loop()
    results: dict[str, str | None] = {}

    for i, sym in enumerate(symbols):
        if i > 0:
            await asyncio.sleep(_DELAY_BETWEEN_FETCHES)
        try:
            result = await _fetch_with_semaphore(loop, sym)
            results[sym] = result
        except Exception as e:
            logger.warning("Earnings fetch failed for %s: %s", sym, e)
            results[sym] = None

    return results


async def _fetch_with_semaphore(loop, symbol: str) -> str | None:
    async with _SEMAPHORE:
        return await loop.run_in_executor(None, _fetch_earnings_for_symbol, symbol)


def _fetch_earnings_for_symbol(symbol: str) -> str | None:
    """Fetch next earnings date for one symbol via yfinance."""
    from app.services.price_service import _yahoo_lookup_symbol

    lookup = _yahoo_lookup_symbol(symbol)
    try:
        ticker = yf.Ticker(lookup)
        info = ticker.info or {}

        ts = info.get("earningsTimestamp")
        if ts:
            return date.fromtimestamp(ts).isoformat()

        return None
    except Exception as e:
        logger.warning("yfinance earnings fetch failed for %s (%s): %s", symbol, lookup, e)
        return None
