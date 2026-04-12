"""REST endpoints for the CSP Screener."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth.session import get_current_user
from app.schemas.screener import ScanFilters, ScanResponse, ScreenerResultOut, WatchlistOut, WatchlistSymbol
from app.services.screener_service import (
    add_symbol,
    get_latest_results,
    get_scan_job_status,
    get_watchlist,
    remove_symbol,
    trigger_scan_job,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screener", tags=["screener"])

_DEFAULT_USER = "default"


def _user_sub(request: Request) -> str:
    """Extract user sub from request, falling back to shared default."""
    user = get_current_user(request)
    if user:
        return user.sub
    return _DEFAULT_USER


@router.get("/watchlist")
async def list_watchlist(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    symbols = await get_watchlist(db, _user_sub(request))
    return WatchlistOut(symbols=symbols)


@router.post("/watchlist")
async def add_watchlist_symbol(
    body: WatchlistSymbol,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        entry = await add_symbol(db, _user_sub(request), body.symbol)
        return {"symbol": entry.symbol, "added": True}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.delete("/watchlist/{symbol}")
async def remove_watchlist_symbol(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await remove_symbol(db, _user_sub(request), symbol)
    return {"symbol": symbol.upper(), "removed": True}


@router.post("/scan")
async def start_scan(
    request: Request,
    db: AsyncSession = Depends(get_db),
    filters: ScanFilters = ScanFilters(),
):
    """Start a background scan job. Returns job_id immediately."""
    user_sub = _user_sub(request)
    symbols = await get_watchlist(db, user_sub)
    if not symbols:
        return ScanResponse(
            scanned_at=datetime.now(UTC).isoformat(),
            watchlist_count=0,
            opportunities_found=0,
            failed_tickers=[],
            avg_iv=0.0,
            total_capital=0.0,
            results=[],
        )
    job_id = await trigger_scan_job(db, user_sub, filters, symbols)
    return {"job_id": job_id, "watchlist_count": len(symbols)}


@router.get("/scan/{job_id}")
async def scan_job_status(job_id: str):
    """Poll scan job status. No DB session needed — reads from in-memory job."""
    job = get_scan_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/results")
async def get_results(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    rows = await get_latest_results(db, _user_sub(request))
    results = [
        ScreenerResultOut(
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
        for r in rows
    ]
    return {"results": results, "count": len(results)}


@router.get("/filters")
async def get_default_filters():
    return ScanFilters()
