"""Tests for import_service.import_csv."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.import_service import import_csv


def _sample_csv():
    return (
        "Header\n"
        "ClientAccountID,Symbol,Underlying,Expiry,Strike,Put/Call,Multiplier,PosQty,PosAvgPrice,MarkPrice,PositionValue\n"
        'U12345,"AAPL  250119P00150000",AAPL,20250119,150,P,100,-1,3.50,2.50,-250\n'
    )


def _sample_trades_csv():
    return (
        "Header\n"
        "ClientAccountID,Symbol,Underlying,Expiry,Strike,Put/Call,TradeDate,Quantity,TradePrice,Proceeds,Commission,NetCash,LevelOfDetail\n"
        'U12345,"AAPL  250119P00150000",AAPL,20250119,150,P,20250110,-1,3.50,350.00,-0.50,349.50,EXECUTION\n'
    )


def _combined_csv():
    return _sample_csv() + "\n" + _sample_trades_csv()


@pytest.mark.asyncio
@patch("app.services.import_service.invalidate_all_caches")
@patch("app.services.import_service.upsert_positions_from_flex", new_callable=AsyncMock)
@patch("app.services.import_service.clear_positions", new_callable=AsyncMock)
@patch("app.services.import_service.get_fx_rate", return_value=1.0)
async def test_import_csv_happy_path(mock_fx, mock_clear, mock_upsert, mock_invalidate):
    mock_upsert.return_value = 1

    db = AsyncMock()
    result = await import_csv(db, _combined_csv(), account_id=1)

    assert result["positions_imported"] == 1
    mock_clear.assert_called_once_with(
        db, 1, user_account_ids=None, auto_commit=False
    )
    mock_upsert.assert_called_once()
    # Single commit + single invalidation
    db.commit.assert_called_once()
    mock_invalidate.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.import_service.invalidate_all_caches")
@patch("app.services.import_service.upsert_positions_from_flex", new_callable=AsyncMock)
@patch("app.services.import_service.clear_positions", new_callable=AsyncMock)
@patch("app.services.import_service.get_fx_rate", return_value=1.0)
async def test_import_csv_rollback_on_failure(mock_fx, mock_clear, mock_upsert, mock_invalidate):
    mock_upsert.side_effect = Exception("DB error")

    db = AsyncMock()
    result = await import_csv(db, _combined_csv(), account_id=1)

    assert result["positions_imported"] == 0
    db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_import_csv_rejects_unauthorized_account():
    db = AsyncMock()
    with pytest.raises(ValueError, match="Not your account"):
        await import_csv(db, _combined_csv(), account_id=1, user_account_ids=[2, 3])


@pytest.mark.asyncio
@patch("app.services.import_service.invalidate_all_caches")
@patch("app.services.import_service.upsert_positions_from_flex", new_callable=AsyncMock)
@patch("app.services.import_service.clear_positions", new_callable=AsyncMock)
@patch("app.services.import_service.get_fx_rate")
async def test_import_csv_fx_conversion(mock_fx, mock_clear, mock_upsert, mock_invalidate):
    """Verify FX rate is applied to monetary fields."""
    mock_fx.return_value = 0.0067  # JPY to USD
    mock_upsert.return_value = 1

    db = AsyncMock()

    jpy_csv = (
        "ClientAccountID,Symbol,UnderlyingSymbol,Expiry,Strike,Put/Call,Multiplier,Quantity,OpenPrice,MarkPrice,PositionValue,AssetClass,Description\n"
        'U12345,"7203  250119P0020000",7203,20250119,2000,P,100,-1,50.00,45.00,-4500,OPT,7203 PUT\n'
    )

    await import_csv(db, jpy_csv, account_id=1)

    # Check that upsert was called with FX-converted data
    call_args = mock_upsert.call_args
    positions = call_args[0][1]  # second positional arg
    assert len(positions) == 1
    # strike should be converted: 2000 * 0.0067
    assert abs(positions[0]["strike"] - 2000 * 0.0067) < 0.01


@pytest.mark.asyncio
@patch("app.services.import_service.invalidate_all_caches")
@patch("app.services.import_service.upsert_positions_from_flex", new_callable=AsyncMock)
@patch("app.services.import_service.clear_positions", new_callable=AsyncMock)
@patch("app.services.import_service.get_fx_rate", return_value=1.0)
async def test_import_csv_single_cache_invalidation(mock_fx, mock_clear, mock_upsert, mock_invalidate):
    """Verify cache is invalidated exactly once per import."""
    mock_upsert.return_value = 1

    db = AsyncMock()
    await import_csv(db, _combined_csv(), account_id=1)

    # invalidate_all_caches should be called exactly once (by import_csv)
    mock_invalidate.assert_called_once()
