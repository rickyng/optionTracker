"""Tests for position_service.upsert_positions_from_flex."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.position_service import upsert_positions_from_flex


def _make_existing_option(account_id=1, symbol="AAPL  250119P00150000"):
    """Create a mock OpenOption."""
    opt = MagicMock()
    opt.account_id = account_id
    opt.symbol = symbol
    opt.mark_price = 2.0
    opt.entry_premium = 3.0
    opt.quantity = -1.0
    opt.multiplier = 100
    opt.current_value = 200.0
    return opt


def _pos_data(account_id=1, symbol="AAPL  250119P00150000"):
    return {
        "account_id": account_id,
        "symbol": symbol,
        "underlying": "AAPL",
        "expiry": "2025-01-19",
        "strike": 150.0,
        "right": "P",
        "quantity": -1.0,
        "multiplier": 100,
        "mark_price": 2.5,
        "entry_premium": 3.5,
        "current_value": 250.0,
        "is_manual": 0,
    }


@pytest.mark.asyncio
async def test_insert_new_position():
    db = AsyncMock()
    # No existing positions
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    count = await upsert_positions_from_flex(db, [_pos_data()])

    assert count == 1
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_existing_position():
    db = AsyncMock()
    existing = _make_existing_option()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing]
    db.execute = AsyncMock(return_value=mock_result)

    count = await upsert_positions_from_flex(db, [_pos_data()])

    assert count == 1
    db.add.assert_not_called()
    db.commit.assert_called_once()
    assert existing.mark_price == 2.5
    assert existing.entry_premium == 3.5


@pytest.mark.asyncio
async def test_filter_by_user_account_ids():
    db = AsyncMock()
    count = await upsert_positions_from_flex(
        db, [_pos_data(account_id=3)], user_account_ids=[1, 2]
    )
    assert count == 0
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_empty_positions():
    db = AsyncMock()
    count = await upsert_positions_from_flex(db, [])
    assert count == 0
    db.execute.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_auto_commit_false():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.position_service.invalidate_all_caches") as mock_inv:
        count = await upsert_positions_from_flex(db, [_pos_data()], auto_commit=False)

    assert count == 1
    db.commit.assert_not_called()
    mock_inv.assert_not_called()


@pytest.mark.asyncio
async def test_auto_commit_true_default():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.position_service.invalidate_all_caches") as mock_inv:
        count = await upsert_positions_from_flex(db, [_pos_data()])

    assert count == 1
    db.commit.assert_called_once()
    mock_inv.assert_called_once()


@pytest.mark.asyncio
async def test_mixed_insert_and_update():
    db = AsyncMock()
    existing = _make_existing_option(symbol="AAPL  250119P00150000")
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing]
    db.execute = AsyncMock(return_value=mock_result)

    positions = [
        _pos_data(symbol="AAPL  250119P00150000"),  # update
        _pos_data(symbol="MSFT  250119P00200000"),  # insert
    ]

    count = await upsert_positions_from_flex(db, positions)
    assert count == 2
    db.add.assert_called_once()  # Only MSFT was new
