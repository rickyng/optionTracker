import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids, require_account_ownership
from app.services import account_service, import_service

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/upload")
async def upload_csv(
    request: Request,
    account_id: int = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    user_account_ids = await require_account_ownership(account_id, request, db)
    content = await file.read()
    csv_text = content.decode("utf-8-sig")
    result = await import_service.import_csv(
        db, csv_text, account_id, user_account_ids=user_account_ids
    )
    return result


@router.post("/discover")
async def discover_csvs(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Auto-discover CSV files from downloads directory."""
    user_account_ids = await get_user_account_ids(request, db)

    if user_account_ids is not None:
        # Find the user's first enabled account
        user_accounts = await account_service.get_enabled_accounts(
            db, user_account_ids=user_account_ids
        )
        if not user_accounts:
            raise HTTPException(status_code=403, detail="No accessible accounts")
        default_account_id = user_accounts[0].id
    else:
        default_account_id = 1

    downloads_dir = os.environ.get("IBKR_DOWNLOADS_DIR", "downloads")
    if not os.path.isdir(downloads_dir):
        return {"error": "Downloads directory not found", "imported": 0}

    results = []
    for filename in os.listdir(downloads_dir):
        if not filename.endswith(".csv"):
            continue
        filepath = os.path.join(downloads_dir, filename)
        with open(filepath) as f:
            csv_text = f.read()
        result = await import_service.import_csv(
            db,
            csv_text,
            default_account_id,
            user_account_ids=user_account_ids,
        )
        results.append({"file": filename, **result})

    return {"imported": len(results), "details": results}
