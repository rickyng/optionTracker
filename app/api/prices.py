from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
from app.services.price_service import fetch_price, fetch_prices_batch
from app.services.yahoo_data_service import refresh_all_underlyings

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/{symbol}")
async def get_price(symbol: str):
    price = await fetch_price(symbol)
    if price is None:
        return {"symbol": symbol, "price": None, "error": "Price not available"}
    return {"symbol": symbol, "price": price}


class BatchRequest(BaseModel):
    symbols: list[str]


@router.post("/batch")
async def get_prices_batch(request: BatchRequest):
    results = await fetch_prices_batch(request.symbols)
    return {"prices": results}


@router.post("/refresh")
async def refresh_prices(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Refresh market data (prices + earnings) for all underlyings.

    Uses consolidated YahooDataService — one yfinance call per symbol.
    Skips symbols with fresh data (fetched today).
    """
    user_account_ids = await get_user_account_ids(request, db)
    results = await refresh_all_underlyings(db, user_account_ids)

    refreshed = len(results)
    return {"refreshed": refreshed, "total_fetched": refreshed}
