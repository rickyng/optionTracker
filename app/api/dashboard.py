import math
from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.exposure import compute_underlying_exposure
from app.api.deps import get_db, get_user_account_ids
from app.schemas.position import Position
from app.schemas.strategy import Strategy
from app.services import position_service, strategy_service
from app.services.earnings_service import get_earnings_dates
from app.services.market_price_service import get_prices
from app.utils.cache import dashboard_summary_cache, user_cache_key

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and math.isinf(obj):
        return "unlimited" if obj > 0 else "-unlimited"
    if isinstance(obj, set):
        return list(obj)
    return obj


async def _load_shared_data(
    db: AsyncSession,
    account_id: int | None,
    user_account_ids: list[int] | None,
    market: str | None = None,
) -> tuple[list[Position], list[Strategy], dict[int, str], dict[str, float | None], dict[str, str | None]]:
    """Load positions, strategies, account names, market prices, and earnings dates in one pass."""
    positions = await position_service.list_positions(
        db, account_id=account_id, market=market, user_account_ids=user_account_ids
    )
    strategies = await strategy_service.get_strategies(
        db, account_id=account_id, positions=positions, user_account_ids=user_account_ids
    )
    # Account names are already populated from the JOIN in list_positions
    account_names = {p.account_id: p.account_name for p in positions} if positions else {}
    underlyings = list({p.underlying for p in positions})
    market_prices = await get_prices(db, underlyings) if underlyings else {}
    earnings_dates = await get_earnings_dates(db, underlyings) if underlyings else {}
    return positions, strategies, account_names, market_prices, earnings_dates


@router.get("/summary")
async def dashboard_summary(
    request: Request,
    account_id: int | None = Query(None),
    risk_margin_pct: float = Query(30),
    market: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    user_key = user_cache_key(user_account_ids)
    cache_key = ("summary", account_id, risk_margin_pct, market, user_key)
    cached = dashboard_summary_cache.get(cache_key)
    if cached is not None:
        return cached

    positions, strategies, account_names, market_prices, earnings_dates = await _load_shared_data(
        db, account_id, user_account_ids, market=market
    )
    result = _sanitize(
        compute_underlying_exposure(
            positions, strategies, account_names, market_prices, risk_margin_pct / 100.0,
            earnings_dates=earnings_dates,
        )
    )
    dashboard_summary_cache.set(cache_key, result)
    return result


@router.get("/accounts")
async def dashboard_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    risk = await strategy_service.get_portfolio_risk(db, user_account_ids=user_account_ids)
    return _sanitize({"accounts": [ar.model_dump() for ar in risk.account_risks]})


@router.get("/summary-multi")
async def dashboard_summary_multi(
    request: Request,
    account_id: int | None = Query(None),
    pcts: str = Query("5,10,20"),
    market: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Compute summary for multiple risk margin percentages in one request.

    Returns a dict keyed by percentage string, each value is the same shape
    as /summary. Avoids N separate API calls from the risk tab.
    """
    user_account_ids = await get_user_account_ids(request, db)
    user_key = user_cache_key(user_account_ids)

    margin_pcts = [int(p.strip()) for p in pcts.split(",") if p.strip().isdigit()]
    if not margin_pcts:
        margin_pcts = [5, 10, 20]

    # Serve whatever we have in cache, only compute missing
    cache_keys = {pct: ("summary", account_id, pct, market, user_key) for pct in margin_pcts}
    results: dict[str, object] = {}
    missing_pcts = []
    for pct in margin_pcts:
        cached = dashboard_summary_cache.get(cache_keys[pct])
        if cached is not None:
            results[str(pct)] = cached
        else:
            missing_pcts.append(pct)

    if not missing_pcts:
        return results

    # Fetch shared data once for all missing percentages
    positions, strategies, account_names, market_prices, earnings_dates = await _load_shared_data(
        db, account_id, user_account_ids, market=market
    )

    for pct in missing_pcts:
        result = _sanitize(
            compute_underlying_exposure(
                positions, strategies, account_names, market_prices, pct / 100.0,
                earnings_dates=earnings_dates,
            )
        )
        dashboard_summary_cache.set(cache_keys[pct], result)
        results[str(pct)] = result

    return results


@router.get("/underlyings")
async def dashboard_underlyings(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    strategies = await strategy_service.get_strategies(db, user_account_ids=user_account_ids)
    by_underlying: dict[str, list] = defaultdict(list)
    for s in strategies:
        by_underlying[s.underlying].append(_sanitize(s.model_dump()))
    return dict(by_underlying)
