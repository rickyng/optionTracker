# Centralized Data Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize all external data fetching in Settings tab with a unified sync pipeline, 24h cache TTL, and global status banner.

**Architecture:** New `sync_service.py` orchestrates a 4-step pipeline (IBKR → prices → earnings → screener). Dashboard reads from cache; Settings tab triggers syncs. Global banner shows sync status across all tabs.

**Tech Stack:** Python, FastAPI, Dash, SQLAlchemy async, yfinance, IBKR Flex API

---

## File Structure

**New files:**
- `app/services/sync_service.py` — orchestration layer for 4-step sync pipeline
- `app/api/sync.py` — REST endpoints: `POST /api/sync/all`, `GET /api/sync/status`
- `tests/unit/test_sync_service.py` — unit tests for sync service

**Modified files:**
- `app/main.py` — register sync router
- `app/dashboard/app.py` — add global banner, sync status store, polling interval
- `app/dashboard/layouts/settings.py` — replace Flex Sync with Sync All Data, add Screener Watchlist
- `app/dashboard/layouts/screener.py` — remove watchlist/scan button, add data age badge
- `app/dashboard/layouts/main.py` — remove Refresh Prices button
- `app/dashboard/callbacks/__init__.py` — major rewrite:
  - Add sync pipeline callback (replaces handle_sync)
  - Add global banner callback
  - Move watchlist management to settings context
  - Remove refresh_prices callback
  - Remove price refresh from update_overview
  - Modify screener callbacks to read from cache

---

## Task 1: Backend — Sync Service

**Files:**
- Create: `app/services/sync_service.py`
- Test: `tests/unit/test_sync_service.py`

- [ ] **Step 1: Write failing test for sync pipeline job creation**

```python
# tests/unit/test_sync_service.py
import pytest
from datetime import datetime

from app.services.sync_service import (
    get_sync_job_status,
    trigger_sync_all,
    _SYNC_STEPS,
)


@pytest.mark.asyncio
async def test_trigger_sync_all_creates_job():
    """Starting a sync should create a job with initial status."""
    job_id = await trigger_sync_all(force=False)
    assert job_id is not None
    assert len(job_id) == 8  # UUID[:8]

    job = get_sync_job_status(job_id)
    assert job is not None
    assert job["status"] == "pending"
    assert job["current_step"] == 0
    assert job["step_name"] == ""
    assert job["total_steps"] == 4


@pytest.mark.asyncio
async def test_sync_step_names():
    """Sync pipeline has 4 named steps."""
    assert len(_SYNC_STEPS) == 4
    assert _SYNC_STEPS[1] == "IBKR Flex"
    assert _SYNC_STEPS[2] == "Stock Prices"
    assert _SYNC_STEPS[3] == "Earnings Dates"
    assert _SYNC_STEPS[4] == "Screener Options"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sync_service.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'app.services.sync_service'"

- [ ] **Step 3: Write sync_service.py skeleton with job tracking**

```python
# app/services/sync_service.py
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


async def _run_sync_pipeline(
    job_id: str,
    force: bool,
    user_account_ids: list[int] | None,
    user_sub: str,
) -> None:
    """Execute the 4-step sync pipeline."""
    # TODO: implement in next task
    _update_job(job_id, status="completed", last_sync=datetime.now(UTC).isoformat())
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_cleanup_job(job_id))
    except RuntimeError:
        pass
```

- [ ] **Step 4: Run test to verify skeleton passes**

Run: `pytest tests/unit/test_sync_service.py -v`
Expected: PASS (job creation tests pass)

- [ ] **Step 5: Write test for Metadata cache checking**

```python
# tests/unit/test_sync_service.py (append)
import pytest
from datetime import datetime, timedelta

from app.services.sync_service import _is_step_stale, _CACHE_TTL_HOURS


@pytest.mark.asyncio
async def test_is_step_stale_with_no_metadata(db_session):
    """Step is stale if no metadata entry exists."""
    stale = await _is_step_stale(db_session, "sync_ibkr_last_run")
    assert stale is True


@pytest.mark.asyncio
async def test_is_step_stale_with_fresh_metadata(db_session):
    """Step is fresh if metadata timestamp is within TTL."""
    from app.models.metadata import Metadata

    now = datetime.now().isoformat()
    db_session.add(Metadata(key="sync_ibkr_last_run", value=now, updated_at=now))
    await db_session.commit()

    stale = await _is_step_stale(db_session, "sync_ibkr_last_run")
    assert stale is False


@pytest.mark.asyncio
async def test_is_step_stale_with_old_metadata(db_session):
    """Step is stale if metadata timestamp is older than TTL."""
    from app.models.metadata import Metadata

    old_time = (datetime.now() - timedelta(hours=_CACHE_TTL_HOURS + 1)).isoformat()
    db_session.add(Metadata(key="sync_ibkr_last_run", value=old_time, updated_at=old_time))
    await db_session.commit()

    stale = await _is_step_stale(db_session, "sync_ibkr_last_run")
    assert stale is True
```

- [ ] **Step 6: Implement cache TTL checking**

```python
# app/services/sync_service.py (add after imports)

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
```

- [ ] **Step 7: Run cache tests**

Run: `pytest tests/unit/test_sync_service.py::test_is_step_stale -v`
Expected: FAIL (need db_session fixture)

- [ ] **Step 8: Add test fixture for async DB session**

```python
# tests/unit/test_sync_service.py (add at top after imports)
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session


@pytest.fixture
async def db_session():
    """Async DB session for tests."""
    async with async_session() as session:
        yield session
```

- [ ] **Step 9: Run tests again**

Run: `pytest tests/unit/test_sync_service.py::test_is_step_stale -v`
Expected: PASS

- [ ] **Step 10: Write test for step execution order**

```python
# tests/unit/test_sync_service.py (append)

import pytest
from unittest.mock import AsyncMock, patch

from app.services.sync_service import _run_sync_pipeline, _SYNC_STEPS


@pytest.mark.asyncio
async def test_sync_pipeline_runs_steps_in_order():
    """Pipeline executes steps 1→2→3→4."""
    job_id = "test-job"

    # Setup job state
    from app.services.sync_service import _sync_jobs
    _sync_jobs[job_id] = {
        "status": "pending",
        "current_step": 0,
        "step_name": "",
        "total_steps": 4,
        "retry_count": 0,
        "error": None,
        "force": True,
        "user_account_ids": None,
        "user_sub": "test",
        "completed_steps": [],
    }

    # Mock each step
    with patch("app.services.sync_service._step_ibkr", new_callable=AsyncMock) as mock_ibkr, \
         patch("app.services.sync_service._step_prices", new_callable=AsyncMock) as mock_prices, \
         patch("app.services.sync_service._step_earnings", new_callable=AsyncMock) as mock_earnings, \
         patch("app.services.sync_service._step_screener", new_callable=AsyncMock) as mock_screener:

        mock_ibkr.return_value = True
        mock_prices.return_value = True
        mock_earnings.return_value = True
        mock_screener.return_value = True

        await _run_sync_pipeline(job_id, force=True, user_account_ids=None, user_sub="test")

        # Verify order: IBKR called first, screener called last
        assert mock_ibkr.called
        assert mock_prices.called
        assert mock_earnings.called
        assert mock_screener.called

        job = _sync_jobs[job_id]
        assert job["status"] == "completed"
        assert len(job["completed_steps"]) == 4
```

- [ ] **Step 11: Implement pipeline execution**

```python
# app/services/sync_service.py (replace _run_sync_pipeline)

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
            (1, "IBKR Flex", _step_ibkr),
            (2, "Stock Prices", _step_prices),
            (3, "Earnings Dates", _step_earnings),
            (4, "Screener Options", _step_screener),
        ]

        for step_num, step_name, step_fn in steps:
            _update_job(job_id, current_step=step_num, step_name=step_name)

            # Check if step should run (stale or forced)
            cache_key = f"sync_{step_name.lower().replace(' ', '_')}_last_run"
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
                _update_job(job_id, status="error", error=f"Step {step_num} failed: {job.get('error')}")
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
    job = _sync_jobs[job_id]

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


# Placeholder step functions (implement in next task)
async def _step_ibkr(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 1: Download positions from IBKR Flex."""
    return True  # TODO


async def _step_prices(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 2: Fetch stock prices from Yahoo."""
    return True  # TODO


async def _step_earnings(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 3: Fetch earnings dates from Yahoo."""
    return True  # TODO


async def _step_screener(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 4: Fetch options chains for screener watchlist."""
    return True  # TODO
```

- [ ] **Step 12: Run pipeline order test**

Run: `pytest tests/unit/test_sync_service.py::test_sync_pipeline_runs_steps_in_order -v`
Expected: PASS

- [ ] **Step 13: Implement Step 1 - IBKR Flex**

```python
# app/services/sync_service.py (replace _step_ibkr)

async def _step_ibkr(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 1: Download positions from IBKR Flex for all enabled accounts."""
    from app.services import account_service
    from app.services.flex_service import trigger_flex_download, get_job_status

    async with async_session() as db:
        accounts = await account_service.get_enabled_accounts(db, user_account_ids)

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
                    # Don't fail entire sync — continue with other accounts

            if all_done:
                break

            await asyncio.sleep(5)  # Poll interval

        logger.info("IBKR Flex sync complete for %d accounts", len(accounts))
        return True
```

- [ ] **Step 14: Implement Step 2 - Stock Prices**

```python
# app/services/sync_service.py (replace _step_prices)

async def _step_prices(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 2: Fetch stock prices for all underlyings + screener watchlist."""
    from app.models.open_option import OpenOption
    from app.models.screener import ScreenerWatchlist
    from app.services.yahoo_data_service import refresh_if_stale

    async with async_session() as db:
        # Collect underlyings from positions
        query = select(OpenOption.underlying).distinct()
        if user_account_ids:
            query = query.where(OpenOption.account_id.in_(user_account_ids))
        result = await db.execute(query)
        position_symbols = [row[0] for row in result.all()]

        # Collect watchlist symbols
        watchlist_query = select(ScreenerWatchlist.symbol).where(ScreenerWatchlist.user_sub == user_sub)
        watchlist_result = await db.execute(watchlist_query)
        watchlist_symbols = [row[0] for row in watchlist_result.all()]

        # Combine unique symbols
        all_symbols = sorted(set(position_symbols + watchlist_symbols))

        if not all_symbols:
            logger.info("No symbols to refresh prices for")
            return True

        # Refresh stale symbols via YahooDataService
        results = await refresh_if_stale(db, all_symbols)
        logger.info("Price refresh complete: %d/%d symbols updated", len(results), len(all_symbols))
        return True
```

- [ ] **Step 15: Implement Step 3 - Earnings Dates**

```python
# app/services/sync_service.py (replace _step_earnings)

async def _step_earnings(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 3: Fetch earnings dates for screener watchlist only."""
    from app.models.screener import ScreenerWatchlist
    from app.services.earnings_service import refresh_earnings_dates

    async with async_session() as db:
        # Only watchlist symbols need earnings dates (spec requirement)
        watchlist_query = select(ScreenerWatchlist.symbol).where(ScreenerWatchlist.user_sub == user_sub)
        watchlist_result = await db.execute(watchlist_query)
        symbols = [row[0] for row in watchlist_result.all()]

        if not symbols:
            logger.info("No watchlist symbols to refresh earnings for")
            return True

        results = await refresh_earnings_dates(db, symbols)
        logger.info("Earnings refresh complete: %d symbols", len(results))
        return True
```

- [ ] **Step 16: Implement Step 4 - Screener Options**

```python
# app/services/sync_service.py (replace _step_screener)

async def _step_screener(job_id: str, user_account_ids: list[int] | None, user_sub: str) -> bool:
    """Step 4: Fetch options chains for screener watchlist."""
    from app.models.screener import ScreenerWatchlist
    from app.services.screener_service import scan_watchlist
    from app.schemas.screener import ScanFilters

    async with async_session() as db:
        # Get watchlist symbols
        watchlist_query = select(ScreenerWatchlist.symbol).where(ScreenerWatchlist.user_sub == user_sub)
        watchlist_result = await db.execute(watchlist_query)
        symbols = [row[0] for row in watchlist_result.all()]

        if not symbols:
            logger.info("No watchlist symbols to scan")
            return True

        # Run scan with default filters (client-side filtering later)
        filters = ScanFilters()  # Use defaults
        results, failed = await scan_watchlist(db, user_sub, filters)

        logger.info("Screener scan complete: %d results, %d failed", len(results), len(failed))
        return True
```

- [ ] **Step 17: Run all sync_service tests**

Run: `pytest tests/unit/test_sync_service.py -v`
Expected: PASS

- [ ] **Step 18: Commit sync service**

```bash
git add app/services/sync_service.py tests/unit/test_sync_service.py
git commit -m "feat: add sync_service for centralized data pipeline"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 2: Backend — Sync API Endpoints

**Files:**
- Create: `app/api/sync.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create sync API router**

```python
# app/api/sync.py
"""REST endpoints for centralized sync."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_user_account_ids
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

    # Get user_sub from request for screener watchlist filtering
    from app.auth.session import get_current_user
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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/last-sync")
async def get_last_sync_time(db: AsyncSession = Depends(get_db)):
    """Get timestamp of last successful full sync."""
    from sqlalchemy import select
    from app.models.metadata import Metadata

    result = await db.execute(
        select(Metadata).where(Metadata.key == "sync_last_run")
    )
    row = result.scalar_one_or_none()
    if not row:
        return {"last_sync": None}
    return {"last_sync": row.value}
```

- [ ] **Step 2: Register sync router in main.py**

Read `app/main.py` and add the sync router import and registration alongside existing routers.

Find the section where routers are registered (around `app.include_router` calls) and add:

```python
from app.api.sync import router as sync_router
app.include_router(sync_router)
```

- [ ] **Step 3: Test sync API manually**

Run: `curl -X POST http://localhost:8001/api/sync/all`
Expected: `{"job_id": "...", "status": "pending", "total_steps": 4}`

- [ ] **Step 4: Commit sync API**

```bash
git add app/api/sync.py app/main.py
git commit -m "feat: add sync API endpoints (/api/sync/all, /api/sync/status)"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 3: Frontend — Dashboard Layout (Banner + Stores)

**Files:**
- Modify: `app/dashboard/app.py`

- [ ] **Step 1: Add sync status store and polling interval to layout**

In `app/dashboard/app.py`, find the `dcc.Store` components in the layout (around line 170-178) and add:

```python
dcc.Store(id="sync-status-store", data={}),
dcc.Interval(id="sync-banner-poll-interval", interval=3000, disabled=True),
```

- [ ] **Step 2: Add global banner div above tabs**

In the same file, find `dbc.Tabs` component (around line 182) and add a banner div before it:

```python
# ── Global Sync Banner ────────────────────────────────────────
html.Div(id="sync-status-banner", style={"marginBottom": "0.5rem"}),
# ── Tab Content ────────────────────────────────────────────────
dbc.Tabs([...])
```

- [ ] **Step 3: Commit dashboard layout changes**

```bash
git add app/dashboard/app.py
git commit -m "feat: add sync status store and global banner to dashboard layout"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 4: Frontend — Settings Tab Layout

**Files:**
- Modify: `app/dashboard/layouts/settings.py`

- [ ] **Step 1: Replace Flex Sync card with Sync All Data section**

In `app/dashboard/layouts/settings.py`, find the "Flex Sync" card (around line 193-211) and replace it with:

```python
# ── Sync All Data ────────────────────────────────────────────
html.Div(style={"height": "1.5rem"}),
card(
    "Sync All Data",
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Button(
                            "Sync All Data",
                            id="sync-all-data-btn",
                            style={
                                "backgroundColor": ACCENT_PROFIT,
                                "borderColor": ACCENT_PROFIT,
                                "color": "#0f0f1a",
                                "fontWeight": 600,
                            },
                        ),
                        html.Span(
                            id="sync-last-time",
                            style={
                                "fontSize": "0.75rem",
                                "color": TEXT_SECONDARY,
                                "marginLeft": "0.75rem",
                            },
                        ),
                    ],
                    width="auto",
                ),
            ],
        ),
        html.Div(id="sync-progress-list", className="mt-3"),
        dcc.Interval(id="settings-stale-check", interval=100, max_intervals=1, disabled=False),
    ],
),
# ── Screener Watchlist ────────────────────────────────────────
html.Div(style={"height": "1.5rem"}),
card(
    "Screener Watchlist",
    [
        html.Div(id="settings-watchlist-tags", className="mb-2"),
        html.Div(
            [
                dcc.Input(
                    id="settings-add-symbol-input",
                    type="text",
                    placeholder="e.g. AAPL",
                    maxLength=10,
                    style=_input_style(),
                ),
                html.Button(
                    "Add",
                    id="settings-add-symbol-btn",
                    n_clicks=0,
                    style={
                        "backgroundColor": TEXT_ACCENT,
                        "color": "#0f0f1a",
                        "border": "none",
                        "borderRadius": "4px",
                        "padding": "0.3rem 0.8rem",
                        "fontWeight": 600,
                        "fontSize": "0.8rem",
                        "cursor": "pointer",
                        "marginLeft": "0.5rem",
                    },
                ),
                html.Span(
                    id="settings-add-symbol-status",
                    style={"fontSize": "0.75rem", "color": ACCENT_WARN, "marginLeft": "0.5rem"},
                ),
            ],
            className="d-flex align-items-center",
        ),
    ],
),
```

- [ ] **Step 2: Remove old Flex Sync section entirely**

Delete the old "Flex Sync" card that was replaced.

- [ ] **Step 3: Import ACCENT_WARN if not present**

Check imports at top of `settings.py` and add `ACCENT_WARN` if missing:

```python
from app.dashboard.tokens import (
    ACCENT_PROFIT,
    ACCENT_WARN,  # Add this if missing
    BG_CARD,
    ...
)
```

- [ ] **Step 4: Commit settings layout changes**

```bash
git add app/dashboard/layouts/settings.py
git commit -m "feat: redesign settings tab with Sync All Data and Screener Watchlist"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 5: Frontend — Screener Tab Layout

**Files:**
- Modify: `app/dashboard/layouts/screener.py`

- [ ] **Step 1: Remove watchlist collapsible section**

Find and delete the `html.Details` section containing watchlist (lines 63-124).

- [ ] **Step 2: Remove Scan button**

Find and delete the Scan button (around line 33-48). Replace the header section with:

```python
# Header
html.Div(
    [
        html.Span(
            "CSP Screener",
            style={
                "fontSize": "1.1rem",
                "fontWeight": 600,
                "color": TEXT_PRIMARY,
            },
        ),
        html.Span(
            id="screener-data-age",
            style={
                "fontSize": "0.8rem",
                "color": TEXT_SECONDARY,
                "marginLeft": "0.75rem",
            },
        ),
    ],
    style={"display": "flex", "alignItems": "center", "marginBottom": "1rem"},
),
```

- [ ] **Step 3: Remove scan-status and scan-btn IDs**

Delete any elements with IDs `scan-btn`, `scan-status`, `scan-loading`, `scan-loading-inner`.

- [ ] **Step 4: Commit screener layout changes**

```bash
git add app/dashboard/layouts/screener.py
git commit -m "feat: remove watchlist and scan button from screener tab"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 6: Frontend — Overview Tab Cleanup

**Files:**
- Modify: `app/dashboard/layouts/main.py`

- [ ] **Step 1: Remove Refresh Prices button**

Find and delete the Refresh Prices button (around lines 99-113). Also delete the `refresh-prices-status` span.

- [ ] **Step 2: Commit overview layout changes**

```bash
git add app/dashboard/layouts/main.py
git commit -m "feat: remove Refresh Prices button from overview tab"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 7: Frontend — Sync + Banner Callbacks

**Files:**
- Modify: `app/dashboard/callbacks/__init__.py`

- [ ] **Step 1: Add global sync banner callback**

Add this callback after the existing `register_all_callbacks` function signature:

```python
# ---- Global Sync Banner ----
@dash_app.callback(
    Output("sync-status-banner", "children"),
    Output("sync-banner-poll-interval", "disabled"),
    Input("sync-status-store", "data"),
    Input("sync-banner-poll-interval", "n_intervals"),
    State("main-tabs", "active_tab"),
)
def render_sync_banner(status_data, n_intervals, active_tab):
    """Render global sync status banner across all tabs."""
    if not status_data:
        # No sync job — show last sync time from API
        try:
            last_sync = _api_get("/api/sync/last-sync")
            if last_sync and last_sync.get("last_sync"):
                ts = last_sync["last_sync"]
                age = _format_age(ts)
                return html.Div(
                    [
                        html.Span(f"Data synced {age}", style={"color": TEXT_SECONDARY, "fontSize": "0.8rem"}),
                        html.A(
                            "Refresh",
                            href="/dashboard",
                            style={"color": TEXT_ACCENT, "fontSize": "0.8rem", "marginLeft": "0.5rem"},
                        ),
                    ],
                    style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
                ), True
        except Exception:
            pass
        return html.Div(), True

    status = status_data.get("status", "")
    current_step = status_data.get("current_step", 0)
    step_name = status_data.get("step_name", "")
    error = status_data.get("error")

    if status == "syncing" or status == "running":
        # Show progress
        return html.Div(
            [
                dbc.Spinner(size="sm", color="primary"),
                html.Span(f" Syncing {step_name} ({current_step}/4)...", style={"color": TEXT_PRIMARY, "fontSize": "0.85rem"}),
            ],
            style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
        ), False  # Keep polling

    if status == "retrying":
        retry_count = status_data.get("retry_count", 0)
        return html.Div(
            [
                dbc.Spinner(size="sm", color="warning"),
                html.Span(f" Retrying {step_name} ({retry_count}/3)...", style={"color": ACCENT_WARN, "fontSize": "0.85rem"}),
            ],
            style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
        ), False

    if status == "completed":
        last_sync = status_data.get("last_sync")
        if last_sync:
            age = _format_age(last_sync)
            return html.Div(
                [
                    html.Span(f"Data synced {age}", style={"color": ACCENT_PROFIT, "fontSize": "0.85rem"}),
                    html.Span(" ✓", style={"color": ACCENT_PROFIT}),
                ],
                style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
            ), True

    if status == "error":
        return html.Div(
            [
                html.Span(f"Sync failed: {error}", style={"color": ACCENT_LOSS, "fontSize": "0.85rem"}),
                html.A("Retry", href="/dashboard", style={"color": TEXT_ACCENT, "marginLeft": "0.5rem"}),
            ],
            style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
        ), True

    return html.Div(), True


def _format_age(ts_str: str) -> str:
    """Format timestamp as human-readable age."""
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
        diff = now - ts
        hours = int(diff.total_seconds() / 3600)
        if hours < 1:
            return "just now"
        if hours == 1:
            return "1h ago"
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return "unknown"
```

- [ ] **Step 2: Add sync pipeline callback (replaces handle_sync)**

Replace the existing `handle_sync` callback (lines 1007-1174) with:

```python
# ---- Sync All Data Pipeline ----
_max_sync_poll_attempts = 100

@dash_app.callback(
    Output("sync-status-store", "data"),
    Output("sync-progress-list", "children"),
    Output("sync-last-time", "children"),
    Output("sync-banner-poll-interval", "disabled"),
    Output("settings-stale-check", "disabled"),
    Input("sync-all-data-btn", "n_clicks"),
    Input("sync-banner-poll-interval", "n_intervals"),
    Input("settings-stale-check", "n_intervals"),
    State("sync-status-store", "data"),
    prevent_initial_call=True,
)
def handle_sync_pipeline(btn_clicks, poll_intervals, stale_check, store_data):
    """Handle Sync All Data button + polling."""
    ctx = dash.callback_context
    triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

    # Case 1: Stale check on settings tab load — auto-trigger if data is old
    if triggered == "settings-stale-check.n_intervals":
        try:
            last_sync = _api_get("/api/sync/last-sync")
            if last_sync and last_sync.get("last_sync"):
                ts = last_sync["last_sync"]
                age_hours = _get_age_hours(ts)
                if age_hours >= 24:
                    # Auto-trigger sync
                    resp = _api_post("/api/sync/all", timeout=10)
                    if resp and resp.ok:
                        data = resp.json()
                        job_id = data.get("job_id")
                        return {"job_id": job_id, "status": "pending"}, [], f"Last: {ts[:19]} (stale)", False, True
            # Data fresh or no last_sync
            return dash.no_update, dash.no_update, dash.no_update, True, True
        except Exception:
            return dash.no_update, dash.no_update, dash.no_update, True, True

    # Case 2: Button click — trigger sync
    if triggered == "sync-all-data-btn.n_clicks" and btn_clicks:
        try:
            resp = _api_post("/api/sync/all", json={"force": False}, timeout=10)
            if resp is None:
                return {}, [html.Small("Network error", style={"color": ACCENT_LOSS})], "", True, dash.no_update
            if not resp.ok:
                return {}, [html.Small(f"Error: {resp.status_code}", style={"color": ACCENT_LOSS})], "", True, dash.no_update
            data = resp.json()
            job_id = data.get("job_id")
            return {"job_id": job_id, "status": "pending"}, [], "", False, dash.no_update
        except Exception as e:
            return {}, [html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})], "", True, dash.no_update

    # Case 3: Poll interval — fetch job status
    job_id = (store_data or {}).get("job_id")
    if not job_id:
        return dash.no_update, dash.no_update, dash.no_update, True, dash.no_update

    try:
        status_data = _api_get(f"/api/sync/status/{job_id}", timeout=10)
        if not status_data:
            # Poll failed — retry
            return store_data, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        status = status_data.get("status")
        current_step = status_data.get("current_step", 0)
        step_name = status_data.get("step_name", "")
        completed = status_data.get("completed_steps", [])
        error = status_data.get("error")

        # Build progress list
        progress_cards = []
        for i in range(1, 5):
            if i in completed:
                badge = dbc.Badge("✓", color="success")
            elif i == current_step and status in ("running", "syncing"):
                badge = dbc.Spinner(size="sm", color="primary")
            elif i == current_step and status == "retrying":
                badge = dbc.Badge("Retrying", color="warning")
            elif status == "error" and i == current_step:
                badge = dbc.Badge("Failed", color="danger")
            else:
                badge = dbc.Badge("Pending", color="secondary")

            step_names = ["IBKR Flex", "Stock Prices", "Earnings Dates", "Screener Options"]
            progress_cards.append(
                html.Div(
                    [html.Span(step_names[i-1], style={"color": TEXT_PRIMARY}), badge],
                    style={"marginRight": "1rem"},
                )
            )

        progress_list = html.Div(progress_cards, className="d-flex flex-wrap")

        last_time = ""
        if status == "completed":
            last_time = f"Last: {status_data.get('last_sync', '')[:19]}"
            return status_data, progress_list, last_time, True, dash.no_update

        if status == "error":
            return status_data, [html.Small(f"Error at step {current_step}: {error}", style={"color": ACCENT_LOSS})], "", True, dash.no_update

        # Still running
        return status_data, progress_list, "", False, dash.no_update

    except Exception as e:
        return store_data, [html.Small(f"Poll error: {e}", style={"color": ACCENT_LOSS})], "", True, dash.no_update


def _get_age_hours(ts_str: str) -> int:
    """Get age in hours from timestamp."""
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
        diff = now - ts
        return int(diff.total_seconds() / 3600)
    except Exception:
        return 999
```

- [ ] **Step 3: Remove old handle_sync callback**

Delete the original `handle_sync` callback function (lines 1007-1174) that was handling Flex sync jobs.

- [ ] **Step 4: Remove sync-job-ids and sync-poll-interval references**

In `app/dashboard/app.py`, remove:
- `dcc.Store(id="sync-job-ids", data=[])`
- `dcc.Interval(id="sync-poll-interval", interval=5000, disabled=True)`

- [ ] **Step 5: Commit sync callbacks**

```bash
git add app/dashboard/callbacks/__init__.py app/dashboard/app.py
git commit -m "feat: add sync pipeline and global banner callbacks"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 8: Frontend — Watchlist + Screener Cache Callbacks

**Files:**
- Modify: `app/dashboard/callbacks/__init__.py`

- [ ] **Step 1: Modify watchlist callback for settings tab context**

Find the `manage_watchlist` callback (around line 1305-1353). Modify the inputs to work from settings tab:

```python
# ---- Watchlist Management (moved to Settings) ----
@dash_app.callback(
    Output("screener-watchlist-store", "data"),
    Output("settings-watchlist-tags", "children"),
    Output("settings-add-symbol-status", "children"),
    Input("settings-add-symbol-btn", "n_clicks"),
    Input({"type": "settings-remove-symbol-btn", "index": dash.dependencies.ALL}, "n_clicks"),
    State("settings-add-symbol-input", "value"),
    prevent_initial_call=True,
)
def manage_settings_watchlist(add_clicks, remove_clicks, new_symbol):
    """Manage watchlist from Settings tab."""
    ctx = dash.callback_context
    triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

    status_msg = ""

    # Remove symbol
    if "settings-remove-symbol-btn" in triggered:
        triggered_id = dash.callback_context.triggered_id
        if isinstance(triggered_id, dict) and triggered_id.get("type") == "settings-remove-symbol-btn":
            sym = triggered_id["index"]
            try:
                _api_delete(f"/api/screener/watchlist/{sym}")
                status_msg = f"Removed {sym}"
            except Exception as e:
                status_msg = f"Failed: {e}"

    # Add symbol
    elif "settings-add-symbol-btn" in triggered and add_clicks and new_symbol:
        symbol_upper = new_symbol.strip().upper()
        if not symbol_upper:
            status_msg = "Enter a symbol"
        else:
            try:
                resp = _api_post("/api/screener/watchlist", json={"symbol": symbol_upper})
                if resp and resp.ok:
                    status_msg = f"Added {symbol_upper}"
                elif resp:
                    detail = resp.json().get("detail", resp.text[:50])
                    status_msg = detail
                else:
                    status_msg = "Network error"
            except Exception as e:
                status_msg = f"Failed: {e}"

    # Fetch current watchlist
    data = _api_get("/api/screener/watchlist")
    symbols = data.get("symbols", []) if data else []

    # Build tags for settings tab
    tags = []
    for sym in symbols:
        tags.append(
            html.Span(
                [
                    html.Span(sym, style={"marginRight": "0.3rem"}),
                    html.Span(
                        "x",
                        id={"type": "settings-remove-symbol-btn", "index": sym},
                        style={
                            "cursor": "pointer",
                            "fontWeight": 700,
                            "fontSize": "0.7rem",
                            "color": TEXT_SECONDARY,
                        },
                    ),
                ],
                style={
                    "backgroundColor": BG_CARD_HEADER,
                    "border": f"1px solid {BORDER}",
                    "borderRadius": "4px",
                    "padding": "0.2rem 0.5rem",
                    "fontSize": "0.8rem",
                    "color": TEXT_PRIMARY,
                    "marginRight": "0.4rem",
                    "display": "inline-block",
                },
            )
        )

    return symbols, tags, status_msg
```

- [ ] **Step 2: Remove old manage_watchlist and render_watchlist_tags**

Delete the original callbacks `manage_watchlist` and `render_watchlist_tags`.

- [ ] **Step 3: Modify screener to read from cache**

Find and delete `handle_scan` callback (lines 1431-1575). Replace with:

```python
# ---- Screener Cache Reader ----
@dash_app.callback(
    Output("screener-results-store", "data"),
    Output("screener-data-age", "children"),
    Output("screener-summary-cards", "children"),
    Input("main-tabs", "active_tab"),
    prevent_initial_call=True,
)
def load_screener_cache(active_tab):
    """Load screener results from DB cache (no on-demand scan)."""
    if active_tab != "suggestions":
        return dash.no_update, dash.no_update, dash.no_update

    try:
        data = _api_get("/api/screener/results", timeout=10)
        if not data:
            return {}, "No cached data", html.Small("Sync in Settings tab", style={"color": TEXT_SECONDARY})

        results = data.get("results", [])
        if not results:
            return {}, "No data", html.Small("No opportunities found", style={"color": TEXT_SECONDARY})

        # Build summary cards
        total_capital = sum(r.get("capital_required", 0) for r in results)
        avg_iv = sum(r.get("iv", 0) for r in results) / len(results) if results else 0

        # Get scanned_at from most recent result
        scanned_at = results[0].get("scanned_at", "") if results else ""

        scan_data = {
            "results": results,
            "watchlist_count": len(set(r.get("symbol") for r in results)),
            "opportunities_found": len(results),
            "avg_iv": avg_iv,
            "total_capital": total_capital,
            "scanned_at": scanned_at,
        }

        age_str = ""
        if scanned_at:
            age = _format_age(scanned_at)
            age_str = f"({age})"

        summary = dbc.Row(
            [
                dbc.Col(kpi_card("Watchlist", str(scan_data["watchlist_count"]), ACCENT_INFO), lg=2, sm=6),
                dbc.Col(kpi_card("Opportunities", str(len(results)), ACCENT_PROFIT), lg=2, sm=6),
                dbc.Col(kpi_card("Avg IV", f"{avg_iv * 100:.1f}%", ACCENT_WARN), lg=2, sm=6),
                dbc.Col(kpi_card("Total Capital", fmt_money(total_capital), ACCENT_PROFIT), lg=2, sm=6),
                dbc.Col(
                    kpi_card("Scanned", scanned_at[:19].replace("T", " "), TEXT_SECONDARY),
                    lg=4,
                    sm=6,
                ),
            ]
        )

        return scan_data, age_str, summary

    except Exception as e:
        return {}, f"Error: {e}", html.Small(str(e), style={"color": ACCENT_LOSS})
```

- [ ] **Step 4: Remove scan-job-store, scan-poll-interval from app.py**

In `app/dashboard/app.py`, remove:
- `dcc.Store(id="scan-job-store", data={})`
- `dcc.Interval(id="scan-poll-interval", interval=5000, disabled=True)`

- [ ] **Step 5: Commit watchlist and screener changes**

```bash
git add app/dashboard/callbacks/__init__.py app/dashboard/app.py
git commit -m "feat: move watchlist to settings, screener reads from cache"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 9: Frontend — Remove Old Code + Final Cleanup

**Files:**
- Modify: `app/dashboard/callbacks/__init__.py`

- [ ] **Step 1: Remove refresh_prices callback**

Find and delete `refresh_prices` callback (lines 497-515).

- [ ] **Step 2: Remove price refresh from update_overview**

In `update_overview` callback (lines 256-494), find the `contextlib.suppress` block that calls `_api_post("/api/prices/refresh")` and delete it:

```python
# DELETE THIS BLOCK:
with contextlib.suppress(Exception):
    _api_post("/api/prices/refresh", timeout=15)
```

- [ ] **Step 3: Remove screener-filters-store if unused**

Check if `screener-filters-store` is still needed. If not, remove from `app/dashboard/app.py`.

- [ ] **Step 4: Remove unused imports**

Clean up unused imports in `callbacks/__init__.py`:
- Remove `contextlib` if no longer used
- Remove any other unused imports

- [ ] **Step 5: Final commit**

```bash
git add app/dashboard/callbacks/__init__.py app/dashboard/app.py
git commit -m "refactor: remove old price refresh and scan callbacks"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Task 10: Integration Testing

- [ ] **Step 1: Start dev server**

Run: `uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload`

- [ ] **Step 2: Test Sync All Data button**

1. Navigate to Settings tab
2. Click "Sync All Data"
3. Verify progress shows 4 steps
4. Verify global banner shows sync progress
5. Verify banner shows "completed" when done

- [ ] **Step 3: Test auto-trigger on stale data**

1. Verify sync auto-triggers when opening Settings if data >24h old

- [ ] **Step 4: Test Screener tab reads from cache**

1. Navigate to Suggestions tab
2. Verify results appear without Scan button
3. Verify data age badge shows

- [ ] **Step 5: Test Overview tab instant load**

1. Navigate to Overview tab
2. Verify no price refresh trigger
3. Verify instant display of cached data

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Final commit with all changes**

```bash
git add -A
git commit -m "feat: complete centralized data sync implementation

- Sync service orchestrates 4-step pipeline (IBKR, prices, earnings, screener)
- Settings tab triggers sync with progress display
- Global banner shows sync status across all tabs
- Screener reads from cache, no on-demand scan
- Overview instant load, no price refresh trigger

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

Before handoff, verify:
- [ ] No "TODO" or "TBD" placeholders in plan
- [ ] All file paths are exact
- [ ] All code snippets are complete
- [ ] All test commands specify expected output
- [ ] Spec coverage: each section has a corresponding task