"""Tests for flex_service in-memory job tracking.

With the flex_jobs table removed, all job tracking is in-memory via a dict.
"""

import pytest

from app.services.flex_service import _jobs, _update_job, get_job_status, trigger_flex_download


@pytest.fixture(autouse=True)
def _clear_jobs():
    """Clear in-memory jobs between tests."""
    _jobs.clear()
    yield
    _jobs.clear()


def test_get_job_status_not_found():
    assert get_job_status("nonexistent") is None


def test_update_job_sets_fields():
    _jobs["abc"] = {"account_id": 1, "status": "pending", "error": None,
                     "positions_imported": 0, "trades_imported": 0}
    _update_job("abc", status="completed", positions_imported=5)
    assert _jobs["abc"]["status"] == "completed"
    assert _jobs["abc"]["positions_imported"] == 5


def test_update_job_ignores_unknown_job():
    _update_job("nonexistent", status="completed")  # should not raise
    assert "nonexistent" not in _jobs


def test_get_job_status_found():
    _jobs["abc"] = {"account_id": 1, "status": "completed", "error": None,
                     "positions_imported": 3, "trades_imported": 2}
    result = get_job_status("abc")
    assert result is not None
    assert result["job_id"] == "abc"
    assert result["account_id"] == 1
    assert result["status"] == "completed"
    assert result["positions_imported"] == 3
    assert result["trades_imported"] == 2


@pytest.mark.asyncio
async def test_trigger_flex_download_creates_job():
    job_id = await trigger_flex_download(
        account_id=1, token="test-token", query_id="q123"
    )
    assert job_id in _jobs
    assert _jobs[job_id]["account_id"] == 1
    assert _jobs[job_id]["status"] == "pending"
    assert get_job_status(job_id) is not None


@pytest.mark.asyncio
async def test_trigger_flex_download_with_user_account_ids():
    job_id = await trigger_flex_download(
        account_id=1, token="t", query_id="q",
        user_account_ids=[1, 2]
    )
    assert _jobs[job_id]["user_account_ids"] == [1, 2]
