from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.utils.http_client import http_client

_logger = logging.getLogger(__name__)

SYMBOL_MAPPING = {
    "BRKB": "BRK-B",
    "BRKA": "BRK-A",
    "BRK.B": "BRK-B",
    "BRK.A": "BRK-A",
    "BRK B": "BRK-B",
    "BRK A": "BRK-A",
}


def _yahoo_lookup_symbol(symbol: str) -> str:
    """Convert symbol to Yahoo Finance lookup format.

    - Applies BRK mapping
    - Purely numeric symbols get .HK suffix for Hong Kong stocks,
      zero-padded to 4 digits (e.g. 388 → 0388.HK, 700 → 0700.HK)
    """
    lookup = SYMBOL_MAPPING.get(symbol, symbol)
    # Purely numeric symbols are HK stocks; Yahoo needs .HK suffix
    if lookup.isdigit():
        lookup = f"{lookup.zfill(4)}.HK"
    return lookup


async def fetch_price(symbol: str) -> float | None:
    """Fetch current stock price. Try Yahoo first, then Alpha Vantage."""
    lookup = _yahoo_lookup_symbol(symbol)
    price = await _fetch_yahoo(lookup)
    if price is None and settings.alphavantage_api_key:
        price = await _fetch_alphavantage(symbol, settings.alphavantage_api_key)
    return price


_BATCH_DEADLINE = 12.0  # seconds for first pass — well under dashboard API timeout
_RETRY_DEADLINE = 8.0  # seconds for second pass (timed-out symbols only)
_BATCH_SEMAPHORE = asyncio.Semaphore(3)  # max concurrent Yahoo Finance requests
_BATCH_DELAY = 0.5  # seconds between batched requests


async def fetch_prices_batch(symbols: list[str]) -> dict[str, float | None]:
    """Fetch prices for multiple symbols with an overall deadline.

    Throttled to avoid Yahoo Finance rate limiting.
    Returns whatever prices resolved; unresolved symbols get None.
    """
    if not symbols:
        return {}

    results: dict[str, float | None] = {}

    async def _throttled_fetch(sym: str) -> tuple[str, float | None]:
        async with _BATCH_SEMAPHORE:
            price = await fetch_price(sym)
        return sym, price

    # --- First pass ---
    tasks = [asyncio.create_task(_throttled_fetch(sym)) for sym in symbols]
    done, pending = await asyncio.wait(tasks, timeout=_BATCH_DEADLINE)

    for task in done:
        try:
            sym, price = task.result()
            results[sym] = price
        except Exception:
            pass

    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        for task in pending:
            try:
                sym, _ = task.result()
                results[sym] = None
            except (Exception, asyncio.CancelledError):
                pass

    # Mark symbols with no result as None
    for sym in symbols:
        if sym not in results:
            results[sym] = None

    # --- Second pass: retry symbols that returned None ---
    retry_symbols = [sym for sym in symbols if results.get(sym) is None]
    if retry_symbols:
        await asyncio.sleep(_BATCH_DELAY)
        retry_tasks = [asyncio.create_task(_throttled_fetch(sym)) for sym in retry_symbols]
        retry_done, retry_pending = await asyncio.wait(retry_tasks, timeout=_RETRY_DEADLINE)

        for task in retry_done:
            try:
                sym, price = task.result()
                if price is not None:
                    results[sym] = price
            except Exception:
                pass

        for task in retry_pending:
            task.cancel()
        if retry_pending:
            await asyncio.gather(*retry_pending, return_exceptions=True)

    return results


async def _fetch_yahoo(symbol: str) -> float | None:
    """Fetch price from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1d", "range": "1d"}
        resp = await http_client.get(url, params=params, timeout=10)
        data = resp.json()
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except Exception as exc:
        _logger.warning("Yahoo fetch failed for %s: %s", symbol, exc)
        return None


async def _fetch_alphavantage(symbol: str, api_key: str) -> float | None:
    """Fetch price from Alpha Vantage."""
    try:
        url = "https://www.alphavantage.co/query"
        params = {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key}
        resp = await http_client.get(url, params=params, timeout=10)
        data = resp.json()
        return float(data["Global Quote"]["05. price"])
    except Exception as exc:
        _logger.warning("AlphaVantage fetch failed for %s: %s", symbol, exc)
        return None
