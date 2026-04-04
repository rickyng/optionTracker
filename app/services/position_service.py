from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.open_option import OpenOption
from app.schemas.position import Position
from app.utils.cache import invalidate_all_caches


async def list_positions(
    db: AsyncSession,
    *,
    account_id: int | None = None,
    underlying: str | None = None,
    user_account_ids: list[int] | None = None,
) -> list[Position]:
    query = select(OpenOption, Account.name).join(Account, OpenOption.account_id == Account.id)
    if user_account_ids is not None:
        query = query.where(OpenOption.account_id.in_(user_account_ids))
    if account_id is not None:
        query = query.where(OpenOption.account_id == account_id)
    if underlying:
        query = query.where(OpenOption.underlying == underlying)
    result = await db.execute(query)
    rows = result.all()
    return [
        Position(
            id=o.id,
            account_id=o.account_id,
            account_name=name,
            symbol=o.symbol,
            underlying=o.underlying,
            expiry=o.expiry,
            strike=o.strike,
            right=o.right,
            quantity=o.quantity,
            mark_price=o.mark_price or 0.0,
            entry_premium=o.entry_premium or 0.0,
            multiplier=o.multiplier or 100,
            is_manual=bool(o.is_manual),
        )
        for o, name in rows
    ]


async def get_position_count(
    db: AsyncSession,
    *,
    account_id: int | None = None,
    user_account_ids: list[int] | None = None,
) -> int:
    query = select(func.count()).select_from(OpenOption)
    if user_account_ids is not None:
        query = query.where(OpenOption.account_id.in_(user_account_ids))
    if account_id is not None:
        query = query.where(OpenOption.account_id == account_id)
    result = await db.execute(query)
    return result.scalar() or 0


async def create_position(
    db: AsyncSession,
    *,
    account_id: int,
    symbol: str,
    underlying: str,
    expiry: str,
    strike: float,
    right: str,
    quantity: float,
    mark_price: float = 0.0,
    entry_premium: float = 0.0,
    multiplier: int = 100,
    notes: str = "",
    is_manual: bool = True,
    user_account_ids: list[int] | None = None,
) -> OpenOption:
    if user_account_ids is not None and account_id not in user_account_ids:
        raise ValueError("Not your account")
    option = OpenOption(
        account_id=account_id,
        symbol=symbol,
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        quantity=quantity,
        multiplier=multiplier,
        mark_price=mark_price,
        entry_premium=entry_premium,
        is_manual=1 if is_manual else 0,
        notes=notes,
    )
    db.add(option)
    await db.commit()
    await db.refresh(option)
    invalidate_all_caches()
    return option


async def clear_positions(
    db: AsyncSession,
    account_id: int,
    *,
    user_account_ids: list[int] | None = None,
    auto_commit: bool = True,
) -> int:
    if user_account_ids is not None and account_id not in user_account_ids:
        return 0
    result = await db.execute(delete(OpenOption).where(OpenOption.account_id == account_id))
    if auto_commit:
        await db.commit()
        invalidate_all_caches()
    return result.rowcount


async def upsert_positions_from_flex(
    db: AsyncSession,
    positions: list[dict],
    *,
    user_account_ids: list[int] | None = None,
) -> int:
    """Bulk insert/update positions from Flex import. Returns count of upserted rows."""
    if not positions:
        return 0

    # Filter to user's accounts when auth is enabled
    if user_account_ids is not None:
        positions = [p for p in positions if p["account_id"] in user_account_ids]
        if not positions:
            return 0

    # Fetch all existing positions for the affected accounts in one query
    account_ids = {p["account_id"] for p in positions}
    symbols = {p["symbol"] for p in positions}
    result = await db.execute(
        select(OpenOption).where(
            OpenOption.account_id.in_(account_ids),
            OpenOption.symbol.in_(symbols),
        )
    )
    existing_map = {(o.account_id, o.symbol): o for o in result.scalars().all()}

    count = 0
    for pos_data in positions:
        key = (pos_data["account_id"], pos_data["symbol"])
        existing_obj = existing_map.get(key)
        if existing_obj:
            for field in ("mark_price", "current_value", "entry_premium", "quantity", "multiplier"):
                if field in pos_data:
                    setattr(existing_obj, field, pos_data[field])
        else:
            obj = OpenOption(**pos_data)
            db.add(obj)
            existing_map[key] = obj
        count += 1
    await db.commit()
    invalidate_all_caches()
    return count
