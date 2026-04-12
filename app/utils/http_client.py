import asyncio

import httpx

from app.config import settings


class HttpClient:
    """Async HTTP client with retry support."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=settings.http_timeout,
                headers={"User-Agent": "IBKROptionsAnalyzer/2.0"},
                follow_redirects=True,
            )
        return self._client

    async def get(self, url: str, params: dict | None = None, timeout: int | None = None) -> httpx.Response:
        client = await self._get_client()
        last_exc: Exception | None = None
        for attempt in range(settings.http_max_retries):
            try:
                resp = await client.get(url, params=params, timeout=timeout or settings.http_timeout)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    raise
                last_exc = e
            except httpx.RequestError as e:
                last_exc = e
            delay = settings.http_retry_delay_ms / 1000 * (2**attempt)
            await asyncio.sleep(delay)
        raise last_exc or httpx.RequestError("Max retries exceeded")

    async def get_raw(
        self, url: str, params: dict | None = None, timeout: int | None = None, max_retries: int = 0
    ) -> str:
        """GET returning raw text content (for CSV/XML responses).

        Args:
            max_retries: Number of retries on transient errors (default 0 — no retry).
        """
        client = await self._get_client()
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = await client.get(url, params=params, timeout=timeout or settings.http_timeout)
                return resp.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    raise
                last_exc = e
            except httpx.RequestError as e:
                last_exc = e
            if attempt < max_retries:
                delay = settings.http_retry_delay_ms / 1000 * (2**attempt)
                await asyncio.sleep(delay)
        if last_exc:
            raise last_exc

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


http_client = HttpClient()
