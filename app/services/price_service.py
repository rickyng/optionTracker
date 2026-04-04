from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import date

from app.config import settings
from app.utils.http_client import http_client

SYMBOL_MAPPING = {
    "BRKB": "BRK-B",
    "BRKA": "BRK-A",
    "BRK.B": "BRK-B",
    "BRK.A": "BRK-A",
}

_MAX_CACHE_SIZE = 200


class _LRUPriceCache:
    """Bounded LRU cache with end-of-day expiry.

    Prices fetched today are valid all day. Automatically expire at midnight.
    """

    def __init__(self, maxsize: int = _MAX_CACHE_SIZE):
        self._store: OrderedDict[str, float] = OrderedDict()
        self._maxsize = maxsize
        self._today = date.today()

    def get(self, symbol: str) -> float | None:
        # Reset cache if day changed
        today = date.today()
        if today != self._today:
            self._store.clear()
            self._today = today
            return None

        price = self._store.get(symbol)
        if price is None:
            return None
        # Move to end (most recently used)
        self._store.move_to_end(symbol)
        return price

    def set(self, symbol: str, price: float) -> None:
        if symbol in self._store:
            self._store.move_to_end(symbol)
        self._store[symbol] = price
        # Evict oldest entries if over max size
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)


_price_cache = _LRUPriceCache()


async def fetch_price(symbol: str) -> float | None:
    """Fetch current stock price with caching. Try Yahoo first, then Alpha Vantage."""
    cached = _price_cache.get(symbol)
    if cached is not None:
        return cached

    lookup = SYMBOL_MAPPING.get(symbol, symbol)
    price = await _fetch_yahoo(lookup)
    if price is None and settings.alphavantage_api_key:
        price = await _fetch_alphavantage(lookup, settings.alphavantage_api_key)

    if price is not None:
        _price_cache.set(symbol, price)
    return price


async def fetch_prices_batch(symbols: list[str]) -> dict[str, float | None]:
    """Fetch prices for multiple symbols in parallel."""
    tasks = [fetch_price(sym) for sym in symbols]
    results = await asyncio.gather(*tasks)
    return dict(zip(symbols, results, strict=True))


async def _fetch_yahoo(symbol: str) -> float | None:
    """Fetch price from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1d", "range": "1d"}
        resp = await http_client.get(url, params=params, timeout=10)
        data = resp.json()
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except Exception:
        return None


async def _fetch_alphavantage(symbol: str, api_key: str) -> float | None:
    """Fetch price from Alpha Vantage."""
    try:
        url = "https://www.alphavantage.co/query"
        params = {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key}
        resp = await http_client.get(url, params=params, timeout=10)
        data = resp.json()
        return float(data["Global Quote"]["05. price"])
    except Exception:
        return None
