from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
from app.services.market_price_service import refresh_all_prices
from app.services.price_service import fetch_price, fetch_prices_batch

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
    """Refresh prices for all underlyings in current positions.

    Fetches from Yahoo Finance/Alpha Vantage, stores in DB.
    Dashboard will use fresh prices after this.
    """
    user_account_ids = await get_user_account_ids(request, db)
    results = await refresh_all_prices(db, user_account_ids)

    refreshed = sum(1 for p in results.values() if p is not None)
    failed = sum(1 for p in results.values() if p is None)

    return {"refreshed": refreshed, "failed": failed, "total": len(results), "prices": results}
