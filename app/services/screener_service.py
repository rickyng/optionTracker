"""CSP Screener service — scan orchestration, yfinance data fetch, watchlist CRUD."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
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
)
from app.config import settings
from app.models.market_price import MarketPrice
from app.models.screener import ScreenerResult, ScreenerWatchlist
from app.schemas.screener import ScanFilters, ScreenerResultOut

_logger = logging.getLogger(__name__)

# Keep strong references to background tasks so they aren't garbage-collected
_running_tasks: set = set()

# In-memory job tracking: job_id → {user_sub, status, progress, ...}
_scan_jobs: dict[str, dict] = {}

# Global rate limit backoff state
_last_rate_limit_time: float = 0.0
_cooldown_applied_time: float = 0.0  # when we last waited for cooldown


def _rate_limit_cooldown() -> float:
    """Get cooldown duration from settings."""
    return settings.yfinance_rate_limit_cooldown


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

    tasks = [_scan_ticker_with_retry(sym, filters) for sym in symbols]
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


async def _scan_ticker_with_retry(
    symbol: str,
    filters: ScanFilters,
    cached_info: dict | None = None,
    max_retries: int = 3,
) -> tuple[str, list[ScreenerResultOut], str | None]:
    """Fetch and screen puts for a single ticker, with retry on rate-limit.

    Returns (symbol, results, error).
    """
    global _last_rate_limit_time

    for attempt in range(max_retries + 1):
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _fetch_and_screen, symbol, filters, cached_info)
            return symbol, result, None
        except Exception as e:
            err_msg = str(e).lower()
            is_rate_limit = "rate" in err_msg or "429" in err_msg or "too many" in err_msg
            if is_rate_limit:
                _last_rate_limit_time = time.time()
                if attempt < max_retries:
                    backoff = settings.yfinance_delay_between_symbols * (2**attempt)  # exponential
                    _logger.warning("Rate limited on %s, retry %d/%d in %ds", symbol, attempt + 1, max_retries, backoff)
                    await asyncio.sleep(backoff)
                    continue
            return symbol, [], str(e)


def _fetch_and_screen(
    symbol: str,
    filters: ScanFilters,
    cached_info: dict | None = None,
) -> list[ScreenerResultOut]:
    """Synchronous: fetch yfinance data and screen puts for one ticker.

    If cached_info is provided (from YahooDataService), skip the ticker.info
    call and only fetch options chains.
    """
    if cached_info:
        price = cached_info.get("price")
        if not price:
            raise ValueError(f"No cached price for {symbol}")
        pe_ratio = cached_info.get("pe_ratio")
        beta = cached_info.get("beta")
        profit_margin = cached_info.get("profit_margin")
        if profit_margin is not None:
            profit_margin = profit_margin * 100
        revenue_growth = cached_info.get("revenue_growth")
        if revenue_growth is not None:
            revenue_growth = revenue_growth * 100
        strong = is_strong_fundamentals(pe_ratio, profit_margin, beta)
        if beta is not None and beta > filters.max_beta:
            return []

        # Still need ticker object for options chains
        ticker = yf.Ticker(symbol)
    else:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
        except Exception as e:
            err_msg = str(e).lower()
            if "401" in err_msg or "crumb" in err_msg:
                raise ValueError("Yahoo Finance auth error — try again later") from e
            if "429" in err_msg or "rate" in err_msg or "too many" in err_msg:
                raise ValueError("Rate limited by Yahoo Finance — try again later") from e
            raise

        if not info:
            raise ValueError(f"No data returned for {symbol}")

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
        raise ValueError(f"No options data for {symbol}")

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

    for i, (exp_str, dte) in enumerate(valid_expirations):
        # Space out yfinance calls to avoid rate limiting
        if i > 0:
            time.sleep(settings.yfinance_delay_between_chains)

        try:
            chain = ticker.option_chain(exp_str)
            if chain is None:
                continue
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

            # Store all valid puts — filtering happens client-side
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


# ---------------------------------------------------------------------------
# Background Job System (mirrors Flex download pattern)
# ---------------------------------------------------------------------------


async def trigger_scan_job(
    db: AsyncSession,
    user_sub: str,
    filters: ScanFilters,
    symbols: list[str],
) -> str:
    """Start a background scan job. Returns job_id immediately."""
    job_id = str(uuid.uuid4())[:8]
    _scan_jobs[job_id] = {
        "user_sub": user_sub,
        "status": "pending",
        "progress": f"0/{len(symbols)}",
        "current_ticker": None,
        "error": None,
        "results": [],
        "failed_tickers": [],
        "total_tickers": len(symbols),
    }

    task = asyncio.create_task(_run_scan_background(job_id, user_sub, filters, symbols))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return job_id


def get_scan_job_status(job_id: str) -> dict | None:
    """Get scan job status as a dict, or None if not found."""
    job = _scan_jobs.get(job_id)
    if not job:
        return None
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "current_ticker": job["current_ticker"],
        "error": job["error"],
        "results": job["results"],
        "failed_tickers": job["failed_tickers"],
        "total_tickers": job["total_tickers"],
    }


def _update_scan_job(job_id: str, **kwargs) -> None:
    """Update in-memory job entry."""
    job = _scan_jobs.get(job_id)
    if not job:
        return
    job.update(kwargs)


async def _cleanup_scan_job(job_id: str, delay: float = 600) -> None:
    """Remove completed job after a delay so the client can still poll."""
    await asyncio.sleep(delay)
    _scan_jobs.pop(job_id, None)


async def _run_scan_background(
    job_id: str,
    user_sub: str,
    filters: ScanFilters,
    symbols: list[str],
) -> None:
    """Execute the scan in background, updating progress per ticker."""
    from app.database import async_session

    try:
        _update_scan_job(job_id, status="running")

        # Reset global rate limit state for this scan job
        global _last_rate_limit_time, _cooldown_applied_time
        _last_rate_limit_time = 0.0
        _cooldown_applied_time = 0.0

        # Load cached fundamentals from YahooDataService (avoids redundant yfinance calls)
        cached_fundamentals: dict[str, dict] = {}
        async with async_session() as db:
            from app.services.yahoo_data_service import refresh_if_stale

            # refresh_if_stale returns {symbol: {price, pe_ratio, beta, profit_margin, revenue_growth}}
            fetched_data = await refresh_if_stale(db, symbols)
            cached_fundamentals.update(fetched_data)

            # For already-fresh symbols not in fetched_data, read price from DB
            result = await db.execute(select(MarketPrice).where(MarketPrice.symbol.in_(symbols)))
            for row in result.scalars().all():
                if row.symbol not in cached_fundamentals:
                    cached_fundamentals[row.symbol] = {"price": row.price}

        all_results: list[ScreenerResultOut] = []
        failed_tickers: list[str] = []

        for i, symbol in enumerate(symbols):
            _update_scan_job(
                job_id,
                progress=f"{i + 1}/{len(symbols)}",
                current_ticker=symbol,
            )

            # Check for global rate limit backoff (only wait once per cooldown window)
            time_since_rate_limit = time.time() - _last_rate_limit_time
            cooldown = _rate_limit_cooldown()
            if (
                _last_rate_limit_time > 0
                and time_since_rate_limit < cooldown
                and _cooldown_applied_time < _last_rate_limit_time
            ):
                wait_time = cooldown - time_since_rate_limit
                _logger.info("Global rate limit backoff: waiting %.1fs before %s", wait_time, symbol)
                _update_scan_job(job_id, status="rate_limited")
                await asyncio.sleep(wait_time)
                _cooldown_applied_time = time.time()
                _update_scan_job(job_id, status="running")

            # Space out requests to avoid yfinance rate limiting
            if i > 0:
                await asyncio.sleep(settings.yfinance_ticker_delay)

            cached_info = cached_fundamentals.get(symbol)
            _, ticker_results, error = await _scan_ticker_with_retry(symbol, filters, cached_info=cached_info)
            if error:
                failed_tickers.append(symbol)
                _logger.warning("Scan failed for %s: %s", symbol, error)
            else:
                all_results.extend(ticker_results)

        # Store results in database
        async with async_session() as db:
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

        # Convert results to dict for JSON serialization in job status
        results_dicts = [r.model_dump() for r in all_results]

        _update_scan_job(
            job_id,
            status="completed",
            progress=f"{len(symbols)}/{len(symbols)}",
            current_ticker=None,
            results=results_dicts,
            failed_tickers=failed_tickers,
        )

        # Schedule cleanup
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_cleanup_scan_job(job_id))
        except RuntimeError:
            pass

    except Exception as e:
        _logger.exception("_run_scan_background failed for job %s", job_id)
        _update_scan_job(job_id, status="failed", error=str(e))
