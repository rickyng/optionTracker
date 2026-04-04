from fastapi import APIRouter
from pydantic import BaseModel

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
