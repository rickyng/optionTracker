import csv
import io

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
from app.services import strategy_service
from app.services.report_service import generate_text_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/text")
async def text_report(
    request: Request,
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    strategies = await strategy_service.get_strategies(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    report = generate_text_report(strategies)
    return PlainTextResponse(report)


@router.get("/positions.csv")
async def positions_csv(
    request: Request,
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from app.services.position_service import list_positions

    user_account_ids = await get_user_account_ids(request, db)
    positions = await list_positions(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "account_name",
            "underlying",
            "expiry",
            "strike",
            "right",
            "quantity",
            "entry_premium",
            "mark_price",
        ],
    )
    writer.writeheader()
    for p in positions:
        writer.writerow(p.model_dump())
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=positions.csv"},
    )


@router.get("/strategies.csv")
async def strategies_csv(
    request: Request,
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    strategies = await strategy_service.get_strategies(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "account_name",
            "type",
            "underlying",
            "expiry",
            "breakeven_price",
            "max_profit",
            "max_loss",
            "risk_level",
        ],
    )
    writer.writeheader()
    for s in strategies:
        writer.writerow(
            {
                "account_name": s.account_name,
                "type": s.type.value,
                "underlying": s.underlying,
                "expiry": s.expiry,
                "breakeven_price": s.breakeven_price,
                "max_profit": s.max_profit,
                "max_loss": "UNLIMITED" if s.max_loss == float("inf") else s.max_loss,
                "risk_level": s.risk_level,
            }
        )
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=strategies.csv"},
    )


@router.get("/summary.csv")
async def summary_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    risk = await strategy_service.get_portfolio_risk(db, user_account_ids=user_account_ids)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "account_id",
            "account_name",
            "strategy_count",
            "max_profit",
            "max_loss",
            "capital_at_risk",
            "expiring_soon",
        ],
    )
    writer.writeheader()
    for ar in risk.account_risks:
        writer.writerow(ar.model_dump())
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=summary.csv"},
    )
