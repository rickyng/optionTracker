import asyncio
import logging
import uuid

from app.config import settings
from app.database import async_session
from app.services.import_service import import_csv
from app.utils.http_client import http_client
from app.utils.xml_parser import parse_flex_send_response, parse_flex_statement_response

logger = logging.getLogger(__name__)

FLEX_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"

# Keep strong references to background tasks so they aren't garbage-collected
_running_tasks: set = set()

# In-memory job tracking: job_id → {account_id, status, error, ...}
_jobs: dict[str, dict] = {}


async def trigger_flex_download(
    account_id: int,
    token: str,
    query_id: str,
    *,
    user_account_ids: list[int] | None = None,
) -> str:
    """Start a Flex download job. Returns job_id."""
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "account_id": account_id,
        "status": "pending",
        "error": None,
        "positions_imported": 0,
        "trades_imported": 0,
        "user_account_ids": user_account_ids,
    }

    task = asyncio.create_task(
        _run_download(job_id, account_id, token, query_id, user_account_ids)
    )
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return job_id


def get_job_status(job_id: str) -> dict | None:
    """Get job status as a dict, or None if not found."""
    job = _jobs.get(job_id)
    if not job:
        return None
    return {
        "job_id": job_id,
        "account_id": job["account_id"],
        "status": job["status"],
        "error": job["error"],
        "positions_imported": job["positions_imported"],
        "trades_imported": job["trades_imported"],
    }


def _update_job(job_id: str, **kwargs) -> None:
    """Update in-memory job entry. Schedule cleanup when job reaches terminal state."""
    job = _jobs.get(job_id)
    if not job:
        return
    job.update(kwargs)
    if kwargs.get("status") in ("completed", "failed"):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_cleanup_job(job_id))
        except RuntimeError:
            pass  # No running event loop


async def _cleanup_job(job_id: str, delay: float = 600) -> None:
    """Remove completed/failed job after a delay so the client can still poll."""
    await asyncio.sleep(delay)
    _jobs.pop(job_id, None)


async def _run_download(
    job_id: str,
    account_id: int,
    token: str,
    query_id: str,
    user_account_ids: list[int] | None,
) -> None:
    """Execute the full Flex download flow."""
    try:
        _update_job(job_id, status="requesting")

        # Step 1: SendRequest
        send_url = f"{FLEX_BASE}/SendRequest"
        logger.info("SendRequest: token=%s... query_id=%s", token[:8] if token else "None", query_id)
        resp_text = await http_client.get_raw(send_url, params={"t": token, "q": query_id, "v": 3})
        parsed = parse_flex_send_response(resp_text)

        if parsed["status"] != "Success":
            err_detail = parsed.get("error_message") or parsed.get("error_code") or parsed["status"]
            _update_job(job_id, status="failed", error=f"SendRequest failed: {err_detail}")
            return

        ref_code = parsed["reference_code"]

        # Step 2: Poll GetStatement
        _update_job(job_id, status="polling")

        get_url = f"{FLEX_BASE}/GetStatement"
        max_attempts = settings.flex_max_poll_duration // settings.flex_poll_interval

        for _ in range(max_attempts):
            content = await http_client.get_raw(get_url, params={"t": token, "q": ref_code, "v": 3})
            result = parse_flex_statement_response(content)

            if result["status"] == "Success":
                csv_content = result["data"]
                first_lines = "\n".join(csv_content.split("\n")[:3])
                logger.info("Flex CSV headers + sample:\n%s", first_lines)

                # Import into database
                async with async_session() as db:
                    import_result = await import_csv(
                        db,
                        csv_content,
                        account_id,
                        user_account_ids=user_account_ids,
                    )
                _update_job(
                    job_id,
                    status="completed",
                    positions_imported=import_result.get("positions_imported", 0),
                    trades_imported=import_result.get("trades_imported", 0),
                )
                return
            if result["status"] == "Fail":
                _update_job(job_id, status="failed", error="GetStatement returned Fail")
                return

            await asyncio.sleep(settings.flex_poll_interval)

        _update_job(job_id, status="failed", error="Polling timed out")

    except Exception as e:
        logger.exception("_run_download failed for job %s", job_id)
        _update_job(job_id, status="failed", error=str(e))
