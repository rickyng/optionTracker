"""CSP Screener service — scan orchestration, yfinance data fetch, watchlist CRUD."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import yfinance as yf
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.option_greeks import (
    black_scholes_put_delta,
    calc_ann_roc,
    calc_otm_pct,
    calc_rating,
    is_strong_fundamentals,
    passes_filters,
)
from app.models.screener import ScreenerResult, ScreenerWatchlist
from app.schemas.screener import ScanFilters, ScreenerResultOut

_logger = logging.getLogger(__name__)

_SEMAPHORE = asyncio.Semaphore(3)

DEFAULT_WATCHLIST = [
    "ADBE",
    "AMZN",
    "AVGO",
    "BRK-B",
    "GOOG",
    "META",
    "MSFT",
    "NFLX",
    "NVDA",
    "ORCL",
    "PEP",
    "PLTR",
    "PYPL",
    "SAP",
    "TSLA",
    "TSM",
    "U",
    "UNH",
    "V",
]


async def get_watchlist(db: AsyncSession, user_sub: str) -> list[str]:
    """Get user's watchlist symbols. Seeds default list if empty."""
    result = await db.execute(select(ScreenerWatchlist.symbol).where(ScreenerWatchlist.user_sub == user_sub))
    symbols = [row[0] for row in result.all()]
    if not symbols:
        await seed_default_watchlist(db, user_sub)
        symbols = DEFAULT_WATCHLIST[:]
    return symbols


async def seed_default_watchlist(db: AsyncSession, user_sub: str) -> None:
    """Insert default watchlist for a new user."""
    for symbol in DEFAULT_WATCHLIST:
        db.add(ScreenerWatchlist(user_sub=user_sub, symbol=symbol))
    await db.commit()


async def add_symbol(db: AsyncSession, user_sub: str, symbol: str) -> ScreenerWatchlist:
    """Add a symbol to user's watchlist."""
    symbol = symbol.upper().strip()
    existing = await db.execute(
        select(ScreenerWatchlist).where(
            ScreenerWatchlist.user_sub == user_sub,
            ScreenerWatchlist.symbol == symbol,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"{symbol} already in watchlist")
    entry = ScreenerWatchlist(user_sub=user_sub, symbol=symbol)
    db.add(entry)
    await db.commit()
    return entry


async def remove_symbol(db: AsyncSession, user_sub: str, symbol: str) -> None:
    """Remove a symbol from user's watchlist."""
    await db.execute(
        delete(ScreenerWatchlist).where(
            ScreenerWatchlist.user_sub == user_sub,
            ScreenerWatchlist.symbol == symbol.upper().strip(),
        )
    )
    await db.commit()


async def get_latest_results(db: AsyncSession, user_sub: str) -> list[ScreenerResult]:
    """Get cached results from the most recent scan for this user."""
    latest = await db.execute(
        select(ScreenerResult.scanned_at)
        .where(ScreenerResult.user_sub == user_sub)
        .order_by(ScreenerResult.scanned_at.desc())
        .limit(1)
    )
    scan_time = latest.scalar_one_or_none()
    if not scan_time:
        return []

    result = await db.execute(
        select(ScreenerResult)
        .where(ScreenerResult.user_sub == user_sub, ScreenerResult.scanned_at == scan_time)
        .order_by(ScreenerResult.ann_roc_pct.desc())
    )
    return list(result.scalars().all())


async def scan_watchlist(
    db: AsyncSession, user_sub: str, filters: ScanFilters
) -> tuple[list[ScreenerResultOut], list[str]]:
    """Scan watchlist for CSP opportunities.

    Returns (results, failed_tickers).
    """
    symbols = await get_watchlist(db, user_sub)
    if not symbols:
        return [], []

    tasks = [_scan_ticker(sym, filters) for sym in symbols]
    tick_results = await asyncio.gather(*tasks)

    all_results: list[ScreenerResultOut] = []
    failed_tickers: list[str] = []

    for symbol, ticker_results, error in tick_results:
        if error:
            failed_tickers.append(symbol)
            _logger.warning("Scan failed for %s: %s", symbol, error)
            continue
        all_results.extend(ticker_results)

    # Delete old results and store new ones
    await db.execute(delete(ScreenerResult).where(ScreenerResult.user_sub == user_sub))
    await db.flush()

    for r in all_results:
        db.add(
            ScreenerResult(
                user_sub=user_sub,
                symbol=r.symbol,
                price=r.price,
                strike=r.strike,
                expiry=r.expiry,
                dte=r.dte,
                bid=r.bid,
                mid=r.mid,
                iv=r.iv,
                delta=r.delta,
                otm_pct=r.otm_pct,
                ann_roc_pct=r.ann_roc_pct,
                capital_required=r.capital_required,
                pe_ratio=r.pe_ratio,
                beta=r.beta,
                profit_margin=r.profit_margin,
                revenue_growth=r.revenue_growth,
                strong_fundamentals=r.strong_fundamentals,
                rating=r.rating,
                rating_label=r.rating_label,
            )
        )
    await db.commit()

    return all_results, failed_tickers


async def _scan_ticker(symbol: str, filters: ScanFilters) -> tuple[str, list[ScreenerResultOut], str | None]:
    """Fetch and screen puts for a single ticker."""
    async with _SEMAPHORE:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _fetch_and_screen, symbol, filters)
            return symbol, result, None
        except Exception as e:
            return symbol, [], str(e)


def _fetch_and_screen(symbol: str, filters: ScanFilters) -> list[ScreenerResultOut]:
    """Synchronous: fetch yfinance data and screen puts for one ticker."""
    ticker = yf.Ticker(symbol)

    info = ticker.info or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        raise ValueError(f"No price for {symbol}")

    pe_ratio = info.get("trailingPE")
    beta = info.get("beta")
    profit_margin = info.get("profitMargins")
    if profit_margin is not None:
        profit_margin = profit_margin * 100
    revenue_growth = info.get("revenueGrowth")
    if revenue_growth is not None:
        revenue_growth = revenue_growth * 100

    strong = is_strong_fundamentals(pe_ratio, profit_margin, beta)

    if beta is not None and beta > filters.max_beta:
        return []

    expirations = ticker.options
    if not expirations:
        raise ValueError(f"No options for {symbol}")

    today = date.today()
    valid_expirations = []
    for exp_str in expirations:
        try:
            exp_date = date.fromisoformat(exp_str)
            dte = (exp_date - today).days
            if filters.min_dte <= dte <= filters.max_dte:
                valid_expirations.append((exp_str, dte))
        except ValueError:
            continue

    valid_expirations = valid_expirations[:3]
    if not valid_expirations:
        return []

    results: list[ScreenerResultOut] = []

    for exp_str, dte in valid_expirations:
        try:
            chain = ticker.option_chain(exp_str)
        except Exception:
            continue

        puts = chain.puts
        if puts is None or puts.empty:
            continue

        for _, put in puts.iterrows():
            strike = put.get("strike")
            bid = put.get("bid")
            ask = put.get("ask")
            iv = put.get("impliedVolatility")

            if strike is None or bid is None or bid <= 0 or iv is None or iv <= 0:
                continue

            mid = (bid + (ask or bid)) / 2
            otm_pct = calc_otm_pct(price, strike)
            ann_roc = calc_ann_roc(bid, strike, dte)
            capital = strike * 100

            time_to_expiry = dte / 365
            delta_raw = black_scholes_put_delta(s=price, k=strike, t=time_to_expiry, r=0.05, sigma=iv)
            delta_abs = abs(delta_raw)

            if not passes_filters(
                iv=iv,
                delta=delta_abs,
                dte=dte,
                otm_pct=otm_pct,
                ann_roc=ann_roc,
                capital=capital,
                max_capital=filters.max_capital,
                min_iv=filters.min_iv,
                min_delta=filters.min_delta,
                max_delta=filters.max_delta,
                min_dte=filters.min_dte,
                max_dte=filters.max_dte,
                min_otm_pct=filters.min_otm_pct,
                min_ann_roc=filters.min_ann_roc,
            ):
                continue

            rating, label = calc_rating(iv=iv, delta=delta_abs, dte=dte, ann_roc=ann_roc, strong_fundamentals=strong)

            results.append(
                ScreenerResultOut(
                    symbol=symbol,
                    price=price,
                    strike=strike,
                    expiry=exp_str,
                    dte=dte,
                    bid=round(bid, 2),
                    mid=round(mid, 2),
                    iv=round(iv, 4),
                    delta=round(delta_abs, 4),
                    otm_pct=round(otm_pct, 2),
                    ann_roc_pct=round(ann_roc, 2),
                    capital_required=capital,
                    pe_ratio=pe_ratio,
                    beta=beta,
                    profit_margin=profit_margin,
                    revenue_growth=revenue_growth,
                    strong_fundamentals=strong,
                    rating=rating,
                    rating_label=label,
                )
            )

    results.sort(key=lambda r: r.ann_roc_pct, reverse=True)
    return results
