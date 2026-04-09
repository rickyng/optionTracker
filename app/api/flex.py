from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
from app.services import account_service
from app.services.flex_service import get_job_status, trigger_flex_download

router = APIRouter(prefix="/api/flex", tags=["flex"])


@router.post("/download")
async def flex_download(
    request: Request,
    account_ids: list[int] | None = None,
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await get_user_account_ids(request, db)

    if account_ids:
        # Filter requested accounts to those the user owns
        if user_account_ids is not None:
            account_ids = [aid for aid in account_ids if aid in user_account_ids]
            if not account_ids:
                raise HTTPException(status_code=403, detail="No accessible accounts")
        accounts = await account_service.list_accounts(db, user_account_ids=account_ids)
    else:
        accounts = await account_service.get_enabled_accounts(
            db, user_account_ids=user_account_ids
        )

    jobs = []
    for account in accounts:
        job_id = await trigger_flex_download(
            account.id,
            account.token,
            account.query_id,
            user_account_ids=user_account_ids,
        )
        jobs.append({"account_id": account.id, "account_name": account.name, "job_id": job_id})

    return {"jobs": jobs}


@router.get("/download/{job_id}")
async def flex_download_status(job_id: str):
    job = get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Auth middleware already validates the request. Job status is in-memory
    # so no DB session needed — avoids Turso timeouts blocking status polls.
    return {
        "status": job["status"],
        "error": job.get("error"),
        "positions_imported": job.get("positions_imported", 0),
        "trades_imported": job.get("trades_imported", 0),
    }
