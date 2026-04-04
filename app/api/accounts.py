from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids, require_account_ownership
from app.auth.session import get_current_user
from app.services import account_service
from app.utils.cache import invalidate_all_caches

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class CreateAccountRequest(BaseModel):
    name: str
    token: str
    query_id: str


@router.get("")
async def list_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)
    accounts = await account_service.list_accounts(db, user_account_ids=user_account_ids)
    return [
        {
            "id": a.id,
            "name": a.name,
            "token": a.token[:4] + "****" if a.token else "",
            "query_id": a.query_id,
            "enabled": bool(a.enabled),
            "created_at": str(a.created_at),
            "updated_at": str(a.updated_at),
        }
        for a in accounts
    ]


@router.post("")
async def create_account(
    request: Request,
    body: CreateAccountRequest,
    db: AsyncSession = Depends(get_db),
):
    auth_user = get_current_user(request)
    user_id = None
    if auth_user:
        from app.services.user_service import get_or_create_user

        db_user = await get_or_create_user(
            db,
            google_sub=auth_user.sub,
            email=auth_user.email or "",
            name=auth_user.name or "",
            picture=auth_user.picture or "",
        )
        user_id = db_user.id
    account = await account_service.create_account(
        db, name=body.name, token=body.token, query_id=body.query_id, user_id=user_id
    )
    invalidate_all_caches()
    return {"id": account.id, "name": account.name}


@router.get("/{account_id}")
async def get_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await require_account_ownership(account_id, request, db)
    account = await account_service.get_account(db, account_id, user_account_ids=user_account_ids)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {
        "id": account.id,
        "name": account.name,
        "token": account.token,
        "query_id": account.query_id,
        "enabled": bool(account.enabled),
    }


@router.put("/{account_id}")
async def update_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    name: str | None = None,
    token: str | None = None,
    query_id: str | None = None,
    enabled: bool | None = None,
):
    user_account_ids = await require_account_ownership(account_id, request, db)
    account = await account_service.get_account(db, account_id, user_account_ids=user_account_ids)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    kwargs = {}
    if name is not None:
        kwargs["name"] = name
    if token is not None:
        kwargs["token"] = token
    if query_id is not None:
        kwargs["query_id"] = query_id
    if enabled is not None:
        kwargs["enabled"] = 1 if enabled else 0
    account = await account_service.update_account(db, account, **kwargs)
    invalidate_all_caches()
    return {"id": account.id, "name": account.name, "enabled": bool(account.enabled)}


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await require_account_ownership(account_id, request, db)
    account = await account_service.get_account(db, account_id, user_account_ids=user_account_ids)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    await account_service.delete_account(db, account)
    invalidate_all_caches()
    return {"deleted": True}
