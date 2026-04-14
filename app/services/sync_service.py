"""Centralized sync orchestration — 4-step pipeline with cache TTL."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.metadata import Metadata

logger = logging.getLogger(__name__)

# In-memory job tracking: job_id → {status, current_step, ...}
_sync_jobs: dict[str, dict] = {}

# Keep strong references to background tasks
_running_tasks: set = set()

# Step definitions
_SYNC_STEPS = {
    1: "IBKR Flex",
    2: "Stock Prices",
    3: "Earnings Dates",
    4: "Screener Options",
}

# Cache TTL in hours
_CACHE_TTL_HOURS = 24


async def trigger_sync_all(
    force: bool = False,
    user_account_ids: list[int] | None = None,
    user_sub: str = "default",
) -> str:
    """Start a sync job. Returns job_id immediately."""
    job_id = str(uuid.uuid4())[:8]
    _sync_jobs[job_id] = {
        "status": "pending",
        "current_step": 0,
        "step_name": "",
        "total_steps": 4,
        "retry_count": 0,
        "error": None,
        "last_sync": None,
        "force": force,
        "user_account_ids": user_account_ids,
        "user_sub": user_sub,
        "completed_steps": [],
    }

    task = asyncio.create_task(
        _run_sync_pipeline(job_id, force, user_account_ids, user_sub)
    )
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)

    return job_id


def get_sync_job_status(job_id: str) -> dict | None:
    """Get job status as dict, or None if not found."""
    job = _sync_jobs.get(job_id)
    if not job:
        return None
    return {
        "job_id": job_id,
        "status": job["status"],
        "current_step": job["current_step"],
        "step_name": job["step_name"],
        "total_steps": job["total_steps"],
        "retry_count": job["retry_count"],
        "error": job["error"],
        "last_sync": job["last_sync"],
        "completed_steps": job["completed_steps"],
    }


def _update_job(job_id: str, **kwargs) -> None:
    """Update in-memory job entry."""
    job = _sync_jobs.get(job_id)
    if not job:
        return
    job.update(kwargs)


async def _cleanup_job(job_id: str, delay: float = 300) -> None:
    """Remove job after delay so client can poll final status."""
    await asyncio.sleep(delay)
    _sync_jobs.pop(job_id, None)


async def _is_step_stale(db: AsyncSession, key: str) -> bool:
    """Check if a sync step is stale (older than TTL)."""
    result = await db.execute(select(Metadata).where(Metadata.key == key))
    row = result.scalar_one_or_none()
    if not row:
        return True
    try:
        ts = datetime.fromisoformat(row.value)
        cutoff = datetime.now(UTC) - timedelta(hours=_CACHE_TTL_HOURS)
        return ts < cutoff
    except (ValueError, TypeError):
        return True


async def _mark_step_complete(db: AsyncSession, key: str) -> None:
    """Record successful step completion in metadata."""
    now = datetime.now(UTC).isoformat()
    result = await db.execute(select(Metadata).where(Metadata.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = now
        row.updated_at = now
    else:
        db.add(Metadata(key=key, value=now, updated_at=now))
    await db.commit()


async def _run_sync_pipeline(
    job_id: str,
    force: bool,
    user_account_ids: list[int] | None,
    user_sub: str,
) -> None:
    """Execute the 4-step sync pipeline with retry logic."""
    try:
        _update_job(job_id, status="running")

        steps = [
            (1, "IBKR Flex", "sync_ibkr_flex_last_run", _step_ibkr),
            (2, "Stock Prices", "sync_stock_prices_last_run", _step_prices),
            (3, "Earnings Dates", "sync_earnings_dates_last_run", _step_earnings),
            (4, "Screener Options", "sync_screener_options_last_run", _step_screener),
        ]

        for step_num, step_name, cache_key, step_fn in steps:
            _update_job(job_id, current_step=step_num, step_name=step_name)

            # Check if step should run (stale or forced)
            async with async_session() as db:
                should_run = force or await _is_step_stale(db, cache_key)

            if not should_run:
                logger.info("Skipping step %d (%s) — cache fresh", step_num, step_name)
                _update_job(job_id, completed_steps=_sync_jobs[job_id]["completed_steps"] + [step_num])
                continue

            # Execute step with retry
            success = await _run_step_with_retry(job_id, step_fn, step_num, user_account_ids, user_sub)

            if not success:
                # Step failed after retries — stop pipeline
                job = _sync_jobs[job_id]
                _update_job(job_id, status="error", error=f"Step {step_num} ({step_name}) failed: {job.get('error')}")
                return

            # Mark step complete in metadata
            async with async_session() as db:
                await _mark_step_complete(db, cache_key)

            _update_job(job_id, completed_steps=_sync_jobs[job_id]["completed_steps"] + [step_num])

        # All steps completed
        _update_job(job_id, status="completed", last_sync=datetime.now(UTC).isoformat())

    except Exception as e:
        logger.exception("Sync pipeline failed for job %s", job_id)
        _update_job(job_id, status="error", error=str(e))

    finally:
        # Schedule cleanup
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_cleanup_job(job_id))
        except RuntimeError:
            pass


async def _run_step_with_retry(
    job_id: str,
    step_fn,
    step_num: int,
    user_account_ids: list[int] | None,
    user_sub: str,
    max_retries: int = 3,
) -> bool:
    """Run a step with automatic retry on transient errors."""
    for attempt in range(max_retries + 1):
        try:
            _update_job(job_id, retry_count=attempt)

            success = await step_fn(job_id, user_account_ids, user_sub)
            if success:
                return True

        except Exception as e:
            err_msg = str(e).lower()
            is_rate_limit = "rate" in err_msg or "429" in err_msg or "too many" in err_msg
            is_timeout = "timeout" in err_msg

            if is_rate_limit and attempt < max_retries:
                backoff = 60 * (attempt + 1)  # 60s, 120s, 180s
                logger.warning("Rate limit on step %d, retry %d/%d in %ds", step_num, attempt + 1, max_retries, backoff)
                _update_job(job_id, status="retrying")
                await asyncio.sleep(backoff)
                _update_job(job_id, status="running")
                continue

            if is_timeout and attempt < max_retries:
                logger.warning("Timeout on step %d, retry %d/%d immediately", step_num, attempt + 1, max_retries)
                continue

            # Auth error or max retries exhausted
            _update_job(job_id, error=str(e))
            return False

    return False


async def _step_ibkr(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 1: Download positions from IBKR Flex for all enabled accounts."""
    from app.services import account_service
    from app.services.flex_service import trigger_flex_download, get_job_status

    async with async_session() as db:
        accounts = await account_service.get_enabled_accounts(db, user_account_ids=user_account_ids)

        if not accounts:
            logger.info("No enabled accounts to sync")
            return True

        # Trigger downloads for each account
        flex_job_ids = []
        for account in accounts:
            flex_job_id = await trigger_flex_download(
                account.id,
                account.token,
                account.query_id,
                user_account_ids=user_account_ids,
            )
            flex_job_ids.append((account.name, flex_job_id))

    # Poll each flex job until complete
    max_polls = 30
    for poll in range(max_polls):
        all_done = True
        for account_name, flex_job_id in flex_job_ids:
            status = get_job_status(flex_job_id)
            if status and status["status"] in ("pending", "requesting", "polling"):
                all_done = False
            elif status and status["status"] == "failed":
                logger.warning("IBKR Flex failed for %s: %s", account_name, status.get("error"))

        if all_done:
            break

        await asyncio.sleep(5)

    logger.info("IBKR Flex sync complete for %d accounts", len(accounts))
    return True


async def _step_prices(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 2: Fetch stock prices for all underlyings."""
    from app.services.market_price_service import refresh_all_prices

    async with async_session() as db:
        results = await refresh_all_prices(db, user_account_ids=user_account_ids)
        logger.info("Price refresh complete: %d symbols", len(results))
        return True


async def _step_earnings(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 3: Fetch earnings dates."""
    from app.services.earnings_service import refresh_all_earnings_dates

    async with async_session() as db:
        results = await refresh_all_earnings_dates(db, user_account_ids=user_account_ids)
        logger.info("Earnings refresh complete: %d symbols", len(results))
        return True


async def _step_screener(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 4: Fetch options chains for screener watchlist."""
    from app.services.screener_service import trigger_scan_job, get_scan_job_status, get_watchlist
    from app.schemas.screener import ScanFilters

    async with async_session() as db:
        symbols = await get_watchlist(db, user_sub)

        if not symbols:
            logger.info("No watchlist symbols to scan")
            return True

        filters = ScanFilters()
        scan_job_id = await trigger_scan_job(db, user_sub, filters, symbols)

    # Poll scan job until complete
    max_polls = 60
    for poll in range(max_polls):
        status = get_scan_job_status(scan_job_id)
        if status and status["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(5)

    logger.info("Screener scan complete for user %s", user_sub)
    return True
