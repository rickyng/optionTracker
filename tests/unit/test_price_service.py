"""Tests for fetch_prices_batch deadline and retry behavior."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.price_service import fetch_prices_batch


@pytest.mark.asyncio
class TestFetchPricesBatchDeadline:
    async def test_empty_symbols_returns_empty(self):
        result = await fetch_prices_batch([])
        assert result == {}

    async def test_batch_respects_deadline_on_slow_fetch(self):
        """A fetch that would take 60s should be cancelled within the deadline."""

        async def slow_fetch(sym):
            await asyncio.sleep(60)
            return 100.0

        with patch("app.services.price_service.fetch_price", side_effect=slow_fetch):
            result = await fetch_prices_batch(["AAPL"])
            assert result["AAPL"] is None

    async def test_successful_fetch_returned_within_deadline(self):
        with patch(
            "app.services.price_service.fetch_price",
            new_callable=AsyncMock,
            return_value=150.0,
        ):
            result = await fetch_prices_batch(["AAPL"])
            assert result["AAPL"] == 150.0

    async def test_mixed_success_and_failure(self):
        call_count = {"AMZN": 0}

        async def mock_fetch(sym):
            if sym == "AMZN":
                call_count["AMZN"] += 1
                if call_count["AMZN"] <= 1:
                    await asyncio.sleep(60)  # exceed first-pass deadline
                    return None
                return 185.0
            return 150.0

        with patch("app.services.price_service.fetch_price", side_effect=mock_fetch):
            result = await fetch_prices_batch(["AAPL", "AMZN"])
            assert result["AAPL"] == 150.0
