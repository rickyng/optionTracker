from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids, require_account_ownership
from app.services import position_service

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("")
async def list_positions(
    request: Request,
    account_id: int | None = Query(None),
    underlying: str | None = Query(None),
    market: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    positions = await position_service.list_positions(
        db, account_id=account_id, underlying=underlying, market=market, user_account_ids=user_account_ids
    )
    return [p.model_dump() for p in positions]


@router.get("/count")
async def get_position_count(
    request: Request,
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    count = await position_service.get_position_count(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    return {"count": count}


@router.post("")
async def create_position(
    account_id: int,
    symbol: str,
    underlying: str,
    expiry: str,
    strike: float,
    right: str,
    quantity: float,
    request: Request,
    mark_price: float = 0.0,
    entry_premium: float = 0.0,
    notes: str = "",
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await require_account_ownership(account_id, request, db)
    option = await position_service.create_position(
        db,
        account_id=account_id,
        symbol=symbol,
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        quantity=quantity,
        mark_price=mark_price,
        entry_premium=entry_premium,
        notes=notes,
        user_account_ids=user_account_ids,
    )
    return {"id": option.id}


@router.delete("/{account_id}")
async def clear_positions(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await require_account_ownership(account_id, request, db)
    count = await position_service.clear_positions(db, account_id, user_account_ids=user_account_ids)
    return {"deleted": count}
