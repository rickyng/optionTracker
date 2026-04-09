"""Tests for market_price_service DB-backed price caching."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.market_price_service import get_prices, refresh_prices


@pytest.mark.asyncio
class TestGetPrices:
    async def test_empty_symbols(self):
        db = AsyncMock()
        result = await get_prices(db, [])
        assert result == {}

    async def test_returns_stored_prices(self):
        # Use MagicMock (not AsyncMock) for plain attribute access
        mock_row_1 = MagicMock()
        mock_row_1.symbol = "AAPL"
        mock_row_1.price = 175.0

        mock_row_2 = MagicMock()
        mock_row_2.symbol = "GOOG"
        mock_row_2.price = 140.0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row_1, mock_row_2]

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_prices(db, ["AAPL", "GOOG", "MSFT"])
        assert result["AAPL"] == 175.0
        assert result["GOOG"] == 140.0
        assert result["MSFT"] is None  # Not in DB


@pytest.mark.asyncio
class TestRefreshPrices:
    @patch("app.services.market_price_service.dashboard_summary_cache")
    async def test_stores_fetched_prices(self, mock_cache):
        db = AsyncMock()
        # Mock: no existing rows (scalar_one_or_none returns None)
        mock_existing = MagicMock()
        mock_existing.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_existing

        with patch(
            "app.services.market_price_service.fetch_prices_batch",
            new_callable=AsyncMock,
            return_value={"AAPL": 150.0, "MSFT": 300.0},
        ):
            result = await refresh_prices(db, ["AAPL", "MSFT"])

        assert result["AAPL"] == 150.0
        assert result["MSFT"] == 300.0
        # Should have added 2 new rows to DB
        assert db.add.call_count == 2
        db.commit.assert_called_once()

    async def test_empty_symbols(self):
        db = AsyncMock()
        result = await refresh_prices(db, [])
        assert result == {}
        db.commit.assert_not_called()
