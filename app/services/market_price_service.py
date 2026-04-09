"""Service for managing cached market prices in the database.

Prices are fetched from Yahoo Finance/Alpha Vantage and stored in market_prices table.
Dashboard reads from DB (instant) instead of calling external APIs on every load.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_fx_rate
from app.models.market_price import MarketPrice
from app.services.price_service import fetch_prices_batch
from app.utils.cache import dashboard_summary_cache

logger = logging.getLogger(__name__)


async def get_prices(db: AsyncSession, symbols: list[str]) -> dict[str, float | None]:
    """Get cached prices from DB for given symbols.

    Returns dict with symbol -> price (None if not in DB or stale).
    """
    if not symbols:
        return {}

    result = await db.execute(select(MarketPrice).where(MarketPrice.symbol.in_(symbols)))
    rows = result.scalars().all()

    prices: dict[str, float | None] = {sym: None for sym in symbols}
    for row in rows:
        prices[row.symbol] = row.price

    return prices


async def refresh_prices(db: AsyncSession, symbols: list[str]) -> dict[str, float | None]:
    """Fetch prices for symbols via Yahoo/Alpha Vantage, store in DB, return results.

    This is the "Refresh Prices" action — external API calls happen here.
    """
    if not symbols:
        return {}

    logger.info("Refreshing prices for %d symbols: %s", len(symbols), symbols[:5])

    # Fetch from external APIs
    fetched = await fetch_prices_batch(symbols)

    # Update DB — convert to USD to align with strike prices (imported in USD)
    now = datetime.now(UTC).isoformat()
    for symbol, price in fetched.items():
        if price is not None:
            rate = get_fx_rate(symbol)
            usd_price = price * rate
            if rate != 1.0:
                logger.info("Converted %s price: %.2f × %.4f = %.2f USD", symbol, price, rate, usd_price)
            existing = await db.execute(select(MarketPrice).where(MarketPrice.symbol == symbol))
            row = existing.scalar_one_or_none()
            if row:
                row.price = usd_price
                row.updated_at = now
            else:
                db.add(MarketPrice(symbol=symbol, price=usd_price, updated_at=now))

    await db.commit()

    # Invalidate dashboard cache so new prices are reflected
    dashboard_summary_cache.invalidate()

    refreshed = sum(1 for p in fetched.values() if p is not None)
    failed = sum(1 for p in fetched.values() if p is None)
    logger.info("Price refresh complete: %d refreshed, %d failed", refreshed, failed)

    return fetched


async def refresh_all_prices(
    db: AsyncSession,
    user_account_ids: list[int] | None = None,
) -> dict[str, float | None]:
    """Refresh prices for all underlyings in current positions.

    Called after flex sync/import to ensure prices are fresh.
    """
    from app.models.open_option import OpenOption

    query = select(OpenOption.underlying).distinct()
    if user_account_ids is not None:
        query = query.where(OpenOption.account_id.in_(user_account_ids))

    result = await db.execute(query)
    symbols = sorted([row[0] for row in result.all()])

    return await refresh_prices(db, symbols)