import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_fx_rate
from app.models.trade import Trade
from app.parsers.csv_parser import parse_open_positions_csv, parse_trades_csv
from app.services.position_service import clear_positions, upsert_positions_from_flex
from app.utils.cache import invalidate_all_caches

logger = logging.getLogger(__name__)


def _convert_to_usd(data: dict, underlying: str) -> dict:
    """Convert all monetary fields in data to USD using the FX rate for this underlying."""
    rate = get_fx_rate(underlying)
    if rate == 1.0:
        return data
    monetary_fields = ["strike", "mark_price", "entry_premium", "current_value"]
    converted = dict(data)
    for field in monetary_fields:
        if field in converted and converted[field]:
            converted[field] = converted[field] * rate
    logger.info(
        "Converted %s to USD (rate=%s): %s",
        underlying,
        rate,
        {k: v for k, v in converted.items() if k in monetary_fields},
    )
    return converted


async def import_csv(
    db: AsyncSession,
    csv_content: str,
    account_id: int,
    *,
    user_account_ids: list[int] | None = None,
) -> dict:
    """Import positions from CSV content into the specified account."""
    if user_account_ids is not None and account_id not in user_account_ids:
        raise ValueError("Not your account")
    # Log CSV headers for debugging
    first_line = csv_content.split("\n")[0] if csv_content else ""
    logger.info("CSV import headers: %s", first_line)

    open_positions = parse_open_positions_csv(csv_content, skip_expired=True)
    trades = parse_trades_csv(csv_content)

    position_rows = []
    for rec in open_positions:
        pos_data = {
            "account_id": account_id,
            "symbol": rec.symbol,
            "underlying": rec.underlying_symbol,
            "expiry": rec.expiry,
            "strike": rec.strike,
            "right": rec.put_call,
            "quantity": rec.quantity,
            "multiplier": int(rec.multiplier),
            "mark_price": rec.mark_price,
            "entry_premium": rec.open_price or rec.cost_basis_price,
            "current_value": rec.position_value,
            "is_manual": 0,
        }
        pos_data = _convert_to_usd(pos_data, rec.underlying_symbol)
        position_rows.append(pos_data)

    pos_count = 0
    try:
        # Clear old positions so the latest query fully replaces them (atomic: no auto_commit)
        await clear_positions(db, account_id, user_account_ids=user_account_ids, auto_commit=False)
        pos_count = await upsert_positions_from_flex(db, position_rows, user_account_ids=user_account_ids)
    except Exception as e:
        logger.error("Failed to import positions: %s", e)
        await db.rollback()

    # Also save trades
    trade_count = 0
    trade_objs: list[Trade] = []
    for rec in trades:
        try:
            rate = get_fx_rate(rec.underlying_symbol)
            trade_objs.append(
                Trade(
                    account_id=account_id,
                    trade_date=rec.trade_date,
                    symbol=rec.symbol,
                    underlying=rec.underlying_symbol,
                    expiry=rec.expiry,
                    strike=rec.strike * rate,
                    right=rec.put_call,
                    quantity=rec.quantity,
                    trade_price=rec.trade_price * rate,
                    proceeds=rec.proceeds * rate,
                    commission=rec.commission * rate,
                    net_cash=rec.net_cash * rate,
                )
            )
        except Exception as e:
            logger.error("Failed to import trade %s: %s", rec.symbol, e)
    if trade_objs:
        db.add_all(trade_objs)
    trade_count = len(trade_objs)
    await db.commit()

    # Invalidate caches so dashboard reflects new data
    invalidate_all_caches()

    return {"positions_imported": pos_count, "trades_imported": trade_count}
