from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import AuthUser, get_current_user
from app.database import async_session
from app.models.account import Account


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


def require_user(request: Request) -> AuthUser:
    """Dependency that returns the authenticated user (set by AuthMiddleware).

    Raises 401 if no user is found.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def get_user_account_ids(request: Request, db: AsyncSession) -> list[int] | None:
    """Returns list of account IDs the current user can access.

    Returns None when auth is disabled (= all accounts accessible).
    Returns empty list if user has no accounts.
    Result is cached on request.state to avoid repeated DB queries within
    a single request (e.g. dashboard page load triggers multiple API calls).
    """
    cached = getattr(request.state, "_user_account_ids", _SENTINEL)
    if cached is not _SENTINEL:
        return cached

    auth_user = get_current_user(request)
    if not auth_user:
        request.state._user_account_ids = None
        return None

    from app.services.user_service import get_user_by_sub

    db_user = await get_user_by_sub(db, auth_user.sub)
    if not db_user:
        request.state._user_account_ids = []
        return []

    result = await db.execute(select(Account.id).where(Account.user_id == db_user.id))
    ids = [row[0] for row in result.all()]
    request.state._user_account_ids = ids
    return ids


_SENTINEL = object()


async def require_account_ownership(
    account_id: int, request: Request, db: AsyncSession
) -> list[int] | None:
    """Validate that the current user owns the given account_id.

    Returns user_account_ids (None if auth disabled, list otherwise).
    Raises 403 if the user does not own the account.
    """
    user_account_ids = await get_user_account_ids(request, db)
    if user_account_ids is not None and account_id not in user_account_ids:
        raise HTTPException(status_code=403, detail="Not your account")
    return user_account_ids
