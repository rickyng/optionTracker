"""REST endpoints for centralized sync."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
from app.auth.session import get_current_user
from app.models.metadata import Metadata
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
    return {"job_id": job_id, "status": "pending", "total_steps": 4}


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
