from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account


async def list_accounts(
    db: AsyncSession, *, user_account_ids: list[int] | None = None
) -> list[Account]:
    query = select(Account).order_by(Account.name)
    if user_account_ids is not None:
        query = query.where(Account.id.in_(user_account_ids))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_account(
    db: AsyncSession,
    account_id: int,
    *,
    user_account_ids: list[int] | None = None,
) -> Account | None:
    if user_account_ids is not None:
        result = await db.execute(
            select(Account).where(
                Account.id == account_id,
                Account.id.in_(user_account_ids),
            )
        )
        return result.scalar_one_or_none()
    return await db.get(Account, account_id)


async def create_account(
    db: AsyncSession, *, name: str, token: str, query_id: str, user_id: int | None = None
) -> Account:
    account = Account(name=name, token=token, query_id=query_id, user_id=user_id)
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def update_account(db: AsyncSession, account: Account, **kwargs) -> Account:
    for key, value in kwargs.items():
        setattr(account, key, value)
    await db.commit()
    await db.refresh(account)
    return account


async def delete_account(db: AsyncSession, account: Account) -> None:
    await db.delete(account)
    await db.commit()


async def get_enabled_accounts(
    db: AsyncSession, *, user_account_ids: list[int] | None = None
) -> list[Account]:
    query = select(Account).where(Account.enabled == 1)
    if user_account_ids is not None:
        query = query.where(Account.id.in_(user_account_ids))
    result = await db.execute(query)
    return list(result.scalars().all())
