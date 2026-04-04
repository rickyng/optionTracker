from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.strategy_detector import detect_strategies
from app.schemas.risk import AccountRisk, PortfolioRisk
from app.schemas.strategy import Strategy
from app.services.position_service import list_positions
from app.utils.cache import strategies_cache, user_cache_key


async def get_strategies(
    db: AsyncSession,
    *,
    account_id: int | None = None,
    positions: list | None = None,
    user_account_ids: list[int] | None = None,
) -> list[Strategy]:
    cache_key = ("strategies", account_id, user_cache_key(user_account_ids))
    if positions is None:
        cached = strategies_cache.get(cache_key)
        if cached is not None:
            return cached
        positions = await list_positions(
            db, account_id=account_id, user_account_ids=user_account_ids
        )

    result = detect_strategies(positions)

    strategies_cache.set(cache_key, result)
    return result


async def get_portfolio_risk(
    db: AsyncSession,
    *,
    account_id: int | None = None,
    user_account_ids: list[int] | None = None,
) -> PortfolioRisk:
    strategies = await get_strategies(
        db, account_id=account_id, user_account_ids=user_account_ids
    )
    total_profit = sum(s.max_profit for s in strategies)
    total_loss = sum(s.max_loss if s.max_loss != float("inf") else 0 for s in strategies)
    total_capital = sum(abs(s.max_loss) if s.max_loss != float("inf") else 0 for s in strategies)
    expiring_soon = sum(1 for s in strategies if any(_days_remaining(leg["expiry"]) < 7 for leg in s.legs))

    # Per-account breakdown
    account_map: dict[int, AccountRisk] = {}
    for s in strategies:
        if s.account_id not in account_map:
            account_map[s.account_id] = AccountRisk(
                account_id=s.account_id,
                account_name=s.account_name,
                position_count=0,
                strategy_count=0,
            )
        ar = account_map[s.account_id]
        ar.strategy_count += 1
        ar.position_count += len(s.legs)
        ar.max_profit += s.max_profit
        ar.max_loss += s.max_loss if s.max_loss != float("inf") else 0
        ar.capital_at_risk += abs(s.max_loss) if s.max_loss != float("inf") else 0
        ar.net_premium += sum(
            leg.get("entry_premium", 0) * abs(leg.get("quantity", 0)) * leg.get("multiplier", 100) for leg in s.legs
        )
        if any(_days_remaining(leg["expiry"]) < 7 for leg in s.legs):
            ar.expiring_soon += 1

    return PortfolioRisk(
        total_max_profit=total_profit,
        total_max_loss=total_loss,
        total_capital_at_risk=total_capital,
        positions_expiring_soon=expiring_soon,
        total_strategies=len(strategies),
        account_risks=list(account_map.values()),
    )


def _days_remaining(expiry: str) -> int:
    try:
        parts = expiry.split("-")
        exp = date(int(parts[0]), int(parts[1]), int(parts[2]))
        return max((exp - date.today()).days, 0)
    except (ValueError, IndexError):
        return 999
