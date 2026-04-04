import math

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
from app.services import strategy_service

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def _sanitize(obj):
    """Replace inf/-inf with strings for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and math.isinf(obj):
        return "unlimited" if obj > 0 else "-unlimited"
    return obj


@router.get("")
async def get_strategies(
    request: Request,
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    strategies = await strategy_service.get_strategies(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    return [_sanitize(s.model_dump()) for s in strategies]


@router.get("/risk")
async def get_risk(
    request: Request,
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    risk = await strategy_service.get_portfolio_risk(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    return _sanitize(risk.model_dump())


@router.get("/by-underlying")
async def get_by_underlying(
    request: Request,
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    strategies = await strategy_service.get_strategies(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    by_underlying: dict[str, list] = {}
    for s in strategies:
        by_underlying.setdefault(s.underlying, []).append(_sanitize(s.model_dump()))
    return by_underlying
