"""REST endpoints for centralized sync."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
from app.auth.session import get_current_user
from app.models.account import Account
from app.models.market_price import MarketPrice
from app.models.metadata import Metadata
from app.models.open_option import OpenOption
from app.services.sync_service import get_sync_job_status, trigger_sync_all

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/all")
async def sync_all(
    request: Request,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Trigger full sync pipeline. Returns job_id immediately."""
    user_account_ids = await get_user_account_ids(request, db)

    user = get_current_user(request)
    user_sub = user.sub if user else "default"

    job_id = await trigger_sync_all(
        force=force,
        user_account_ids=user_account_ids,
        user_sub=user_sub,
    )
    return {"job_id": job_id, "status": "pending", "total_steps": 3}


@router.get("/status/{job_id}")
async def sync_status(job_id: str):
    """Poll sync job status. No DB session needed — reads from in-memory job."""
    job = get_sync_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/last-sync")
async def get_last_sync_time(db: AsyncSession = Depends(get_db)):
    """Get timestamp of last successful full sync."""
    result = await db.execute(
        select(Metadata).where(Metadata.key == "sync_last_run")
    )
    row = result.scalar_one_or_none()
    if not row:
        return {"last_sync": None}
    return {"last_sync": row.value}


@router.get("/account-status")
async def get_account_sync_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return position counts and last Flex update time per account."""
    user_account_ids = await get_user_account_ids(request, db)

    # Get accounts
    acct_query = select(Account)
    if user_account_ids is not None:
        acct_query = acct_query.where(Account.id.in_(user_account_ids))
    result = await db.execute(acct_query.order_by(Account.name))
    accounts = result.scalars().all()

    # Count positions per account
    count_query = (
        select(OpenOption.account_id, func.count(OpenOption.id))
        .group_by(OpenOption.account_id)
    )
    if user_account_ids is not None:
        count_query = count_query.where(OpenOption.account_id.in_(user_account_ids))
    result = await db.execute(count_query)
    position_counts = dict(result.all())

    # Get last Flex sync time from metadata
    meta_result = await db.execute(
        select(Metadata).where(Metadata.key == "sync_ibkr_flex_last_run")
    )
    flex_meta = meta_result.scalar_one_or_none()
    last_flex_update = flex_meta.value if flex_meta else None

    accounts_data = []
    for acct in accounts:
        accounts_data.append({
            "id": acct.id,
            "name": acct.name,
            "enabled": bool(acct.enabled),
            "position_count": position_counts.get(acct.id, 0),
            "last_flex_update": last_flex_update,
        })

    return {"accounts": accounts_data}


@router.get("/price-status")
async def get_price_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return market prices, OTM option counts, and last update time per underlying."""
    user_account_ids = await get_user_account_ids(request, db)

    # Single query: count OTM options per underlying
    # OTM puts: strike < price; OTM calls: strike > price
    otm_query = (
        select(
            OpenOption.underlying,
            func.sum(
                case(
                    (
                        and_(OpenOption.right == "P", OpenOption.strike < MarketPrice.price),
                        1,
                    ),
                    else_=0,
                )
            ).label("otm_puts"),
            func.sum(
                case(
                    (
                        and_(OpenOption.right == "C", OpenOption.strike > MarketPrice.price),
                        1,
                    ),
                    else_=0,
                )
            ).label("otm_calls"),
        )
        .join(MarketPrice, MarketPrice.symbol == OpenOption.underlying)
        .group_by(OpenOption.underlying)
        .order_by(OpenOption.underlying)
    )
    if user_account_ids is not None:
        otm_query = otm_query.where(OpenOption.account_id.in_(user_account_ids))

    result = await db.execute(otm_query)
    otm_rows = result.all()

    if not otm_rows:
        return {"symbols": []}

    otm_counts: dict[str, int] = {}
    symbols: list[str] = []
    for row in otm_rows:
        symbol = row[0]
        symbols.append(symbol)
        otm_counts[symbol] = (row[1] or 0) + (row[2] or 0)

    # Get market prices for those underlyings
    price_result = await db.execute(
        select(MarketPrice).where(MarketPrice.symbol.in_(symbols))
    )
    price_rows = {row.symbol: row for row in price_result.scalars().all()}

    # Get last price sync time from metadata
    meta_result = await db.execute(
        select(Metadata).where(Metadata.key == "sync_stock_prices_last_run")
    )
    price_meta = meta_result.scalar_one_or_none()

    symbols_data = []
    for symbol in symbols:
        price_row = price_rows.get(symbol)
        symbols_data.append({
            "symbol": symbol,
            "price": price_row.price if price_row else None,
            "option_count": otm_counts.get(symbol, 0),
            "last_updated": price_row.updated_at if price_row else None,
        })

    return {
        "symbols": symbols_data,
        "last_price_sync": price_meta.value if price_meta else None,
    }
