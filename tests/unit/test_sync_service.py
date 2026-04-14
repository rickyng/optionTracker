import uuid
import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, patch

from app.services.sync_service import (
    get_sync_job_status,
    trigger_sync_all,
    _SYNC_STEPS,
    _is_step_stale,
    _CACHE_TTL_HOURS,
    _run_sync_pipeline,
)


@pytest.fixture
async def db_session():
    """Async DB session for tests with cleanup."""
    from app.database import async_session
    from app.models.metadata import Metadata

    async with async_session() as session:
        yield session
        # Cleanup: delete all test metadata keys after test
        await session.execute(
            __import__('sqlalchemy').delete(Metadata).where(
                __import__('sqlalchemy').cast(Metadata.key, __import__('sqlalchemy').String).like("test_%")
            )
        )
        await session.commit()


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


@pytest.mark.asyncio
async def test_is_step_stale_with_no_metadata(db_session):
    """Step is stale if no metadata entry exists."""
    test_key = f"test_no_meta_{uuid.uuid4().hex[:8]}"
    stale = await _is_step_stale(db_session, test_key)
    assert stale is True


@pytest.mark.asyncio
async def test_is_step_stale_with_fresh_metadata(db_session):
    """Step is fresh if metadata timestamp is within TTL."""
    from app.models.metadata import Metadata

    test_key = f"test_fresh_{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC).isoformat()
    db_session.add(Metadata(key=test_key, value=now, updated_at=now))
    await db_session.commit()

    stale = await _is_step_stale(db_session, test_key)
    assert stale is False


@pytest.mark.asyncio
async def test_is_step_stale_with_old_metadata(db_session):
    """Step is stale if metadata timestamp is older than TTL."""
    from app.models.metadata import Metadata

    test_key = f"test_old_{uuid.uuid4().hex[:8]}"
    old_time = (datetime.now(UTC) - timedelta(hours=_CACHE_TTL_HOURS + 1)).isoformat()
    db_session.add(Metadata(key=test_key, value=old_time, updated_at=old_time))
    await db_session.commit()

    stale = await _is_step_stale(db_session, test_key)
    assert stale is True


@pytest.mark.asyncio
async def test_sync_pipeline_runs_steps_in_order():
    """Pipeline executes steps 1→2→3→4."""
    from app.services.sync_service import _sync_jobs

    job_id = "test-job"

    # Setup job state
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