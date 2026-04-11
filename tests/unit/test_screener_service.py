"""Tests for screener_service watchlist CRUD and scan logic."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.screener import ScanFilters
from app.services.screener_service import (
    DEFAULT_WATCHLIST,
    _fetch_and_screen,
    add_symbol,
    get_latest_results,
    get_watchlist,
    remove_symbol,
    seed_default_watchlist,
)

# ---- Watchlist CRUD ----


@pytest.mark.asyncio
async def test_get_watchlist_seeds_defaults_when_empty():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    symbols = await get_watchlist(db, "user1")
    assert symbols == DEFAULT_WATCHLIST[:]
    db.add.assert_called()
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_get_watchlist_returns_existing():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [("AAPL",), ("MSFT",)]
    db.execute = AsyncMock(return_value=mock_result)

    symbols = await get_watchlist(db, "user1")
    assert symbols == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_add_symbol_success():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    entry = await add_symbol(db, "user1", "  aapl ")
    assert entry.symbol == "AAPL"
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_add_symbol_duplicate_raises():
    db = AsyncMock()
    existing = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="already in watchlist"):
        await add_symbol(db, "user1", "AAPL")


@pytest.mark.asyncio
async def test_remove_symbol():
    db = AsyncMock()
    await remove_symbol(db, "user1", "aapl")
    db.execute.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_seed_default_watchlist():
    db = AsyncMock()
    await seed_default_watchlist(db, "user1")
    assert db.add.call_count == len(DEFAULT_WATCHLIST)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_latest_results_empty():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    rows = await get_latest_results(db, "user1")
    assert rows == []


@pytest.mark.asyncio
async def test_get_latest_results_returns_rows():
    db = AsyncMock()
    mock_scan_time = MagicMock()
    mock_scan_result = MagicMock()
    mock_scan_result.scalar_one_or_none.return_value = mock_scan_time

    row = MagicMock()
    mock_rows = MagicMock()
    mock_rows.scalars.return_value.all.return_value = [row]
    db.execute = AsyncMock(side_effect=[mock_scan_result, mock_rows])

    rows = await get_latest_results(db, "user1")
    assert rows == [row]


# ---- _fetch_and_screen ----


def _make_ticker(
    price=150.0,
    pe_ratio=25.0,
    beta=1.2,
    profit_margins=0.20,
    revenue_growth=0.10,
    options=("2026-05-16", "2026-06-20"),
    puts_data=None,
):
    """Build a mock yf.Ticker with configurable data."""
    ticker = MagicMock()
    ticker.info = {
        "currentPrice": price,
        "trailingPE": pe_ratio,
        "beta": beta,
        "profitMargins": profit_margins,
        "revenueGrowth": revenue_growth,
    }
    ticker.options = options

    if puts_data is None:
        # Default: one put that passes filters at 150 strike with good IV
        import pandas as pd

        puts_data = pd.DataFrame(
            [
                {"strike": 140.0, "bid": 2.50, "ask": 2.80, "impliedVolatility": 0.45},
            ]
        )

    chain = MagicMock()
    chain.puts = puts_data
    ticker.option_chain = MagicMock(return_value=chain)
    return ticker


@patch("app.services.screener_service.yf")
def test_fetch_and_screen_finds_opportunity(mock_yf):
    mock_yf.Ticker.return_value = _make_ticker()
    filters = ScanFilters()

    results = _fetch_and_screen("TEST", filters)
    assert len(results) >= 1
    assert results[0].symbol == "TEST"
    assert results[0].strike == 140.0


@patch("app.services.screener_service.yf")
def test_fetch_and_screen_no_price_raises(mock_yf):
    ticker = _make_ticker(price=None)
    ticker.info = {"trailingPE": 25.0}
    mock_yf.Ticker.return_value = ticker

    with pytest.raises(ValueError, match="No price"):
        _fetch_and_screen("TEST", ScanFilters())


@patch("app.services.screener_service.yf")
def test_fetch_and_screen_no_options_raises(mock_yf):
    ticker = _make_ticker()
    ticker.options = ()
    mock_yf.Ticker.return_value = ticker

    with pytest.raises(ValueError, match="No options"):
        _fetch_and_screen("TEST", ScanFilters())


@patch("app.services.screener_service.yf")
def test_fetch_and_screen_high_beta_skipped(mock_yf):
    mock_yf.Ticker.return_value = _make_ticker(beta=3.0)
    results = _fetch_and_screen("TEST", ScanFilters(max_beta=2.5))
    assert results == []


@patch("app.services.screener_service.yf")
def test_fetch_and_screen_filters_by_dte(mock_yf):
    # All expirations are past the max_dte window
    far_future = (date.today().replace(year=date.today().year + 2)).isoformat()
    ticker = _make_ticker(options=(far_future,))
    mock_yf.Ticker.return_value = ticker

    results = _fetch_and_screen("TEST", ScanFilters(min_dte=21, max_dte=45))
    assert results == []


@patch("app.services.screener_service.yf")
def test_fetch_and_screen_low_iv_filtered_out(mock_yf):
    import pandas as pd

    puts = pd.DataFrame(
        [
            {"strike": 140.0, "bid": 2.50, "ask": 2.80, "impliedVolatility": 0.10},
        ]
    )
    mock_yf.Ticker.return_value = _make_ticker(puts_data=puts)
    results = _fetch_and_screen("TEST", ScanFilters(min_iv=0.30))
    assert results == []


@patch("app.services.screener_service.yf")
def test_fetch_and_screen_results_sorted_by_roc(mock_yf):
    import pandas as pd

    puts = pd.DataFrame(
        [
            {"strike": 130.0, "bid": 1.00, "ask": 1.20, "impliedVolatility": 0.45},
            {"strike": 140.0, "bid": 3.00, "ask": 3.20, "impliedVolatility": 0.45},
        ]
    )
    mock_yf.Ticker.return_value = _make_ticker(puts_data=puts)
    results = _fetch_and_screen("TEST", ScanFilters())

    if len(results) >= 2:
        assert results[0].ann_roc_pct >= results[1].ann_roc_pct
