"""Tests for compute_underlying_exposure in the analysis layer."""

from app.analysis.exposure import compute_underlying_exposure
from app.schemas.position import Position
from app.schemas.strategy import Strategy


def _pos(
    underlying="AAPL",
    strike=150.0,
    right="P",
    quantity=-1.0,
    entry_premium=3.50,
    account_id=1,
) -> Position:
    return Position(
        id=1,
        account_id=account_id,
        account_name="Test",
        symbol="AAPL  250119P00150000",
        underlying=underlying,
        expiry="2025-01-19",
        strike=strike,
        right=right,
        quantity=quantity,
        mark_price=2.0,
        entry_premium=entry_premium,
        multiplier=100,
        is_manual=False,
    )


def _strategy(underlying="AAPL", account_id=1, max_profit=350.0, max_loss=14650.0) -> Strategy:
    return Strategy(
        type="naked_short_put",
        underlying=underlying,
        expiry="2025-01-19",
        legs=[{"entry_premium": 3.50, "quantity": -1, "multiplier": 100}],
        account_id=account_id,
        account_name="Test",
        max_profit=max_profit,
        max_loss=max_loss,
    )


class TestComputeExposure:
    def test_empty_positions(self):
        result = compute_underlying_exposure([], [], {}, {}, 0.3)
        assert result["total_positions"] == 0
        assert result["total_accounts"] == 0
        assert result["total_strategies"] == 0
        assert result["underlying_exposure"] == {}

    def test_short_put_exposure(self):
        positions = [_pos(underlying="AAPL", strike=150.0, right="P", entry_premium=3.50)]
        strategies = [_strategy(underlying="AAPL")]
        market_prices = {"AAPL": 160.0}

        result = compute_underlying_exposure(
            positions, strategies, {1: "Test"}, market_prices, risk_factor=0.3
        )

        assert result["total_positions"] == 1
        assert result["total_accounts"] == 1
        # margin_price = 160 * 0.7 = 112, loss_per_share = 150 - 112 = 38, but max(0, 38) = 38
        # pos_loss = 38 * 100 * 1 = 3800
        aapl = result["underlying_exposure"]["AAPL"]
        assert aapl["est_loss"] == 3800.0
        assert aapl["market_price"] == 160.0
        assert aapl["has_puts"] is True
        assert aapl["has_calls"] is False

    def test_short_call_exposure(self):
        positions = [_pos(underlying="TSLA", strike=200.0, right="C", entry_premium=5.0)]
        strategies = [_strategy(underlying="TSLA")]
        market_prices = {"TSLA": 190.0}

        result = compute_underlying_exposure(
            positions, strategies, {1: "Test"}, market_prices, risk_factor=0.3
        )

        # margin_price = 190 * 1.3 = 247, loss_per_share = 247 - 200 = 47
        # pos_loss = 47 * 100 * 1 = 4700
        tsla = result["underlying_exposure"]["TSLA"]
        assert tsla["est_loss"] == 4700.0
        assert tsla["has_calls"] is True
        assert tsla["has_puts"] is False

    def test_mixed_calls_puts_takes_max_loss(self):
        positions = [
            _pos(underlying="SPY", strike=450.0, right="P", entry_premium=2.0),
            _pos(underlying="SPY", strike=470.0, right="C", entry_premium=3.0),
        ]
        strategies = [_strategy(underlying="SPY")]
        market_prices = {"SPY": 460.0}

        result = compute_underlying_exposure(
            positions, strategies, {1: "Test"}, market_prices, risk_factor=0.3
        )

        spy = result["underlying_exposure"]["SPY"]
        # For put: margin = 460*0.7=322, loss = max(0, 450-322)*100*1 = 12800
        # For call: margin = 460*1.3=598, loss = max(0, 598-470)*100*1 = 12800
        assert spy["has_calls"] is True
        assert spy["has_puts"] is True
        # Mixed: take max, not sum
        assert spy["est_loss"] == max(spy["call_loss"], spy["put_loss"])

    def test_no_market_price_means_zero_loss(self):
        positions = [_pos(underlying="UNK", strike=100.0, right="P")]
        strategies = [_strategy(underlying="UNK")]

        result = compute_underlying_exposure(
            positions, strategies, {1: "Test"}, {}, risk_factor=0.3
        )

        unk = result["underlying_exposure"]["UNK"]
        assert unk["est_loss"] == 0.0
        assert unk["market_price"] is None

    def test_price_unavailable_flag_when_no_market_price(self):
        positions = [_pos(underlying="UNK", strike=100.0, right="P")]
        strategies = [_strategy(underlying="UNK")]

        result = compute_underlying_exposure(
            positions, strategies, {1: "Test"}, {}, risk_factor=0.3
        )

        unk = result["underlying_exposure"]["UNK"]
        assert unk["price_unavailable"] is True
        assert unk["positions"][0]["price_unavailable"] is True
        assert unk["positions"][0]["risk_margin_price"] is None

    def test_price_unavailable_false_when_market_price_exists(self):
        positions = [_pos(underlying="AAPL", strike=150.0, right="P")]
        strategies = [_strategy(underlying="AAPL")]
        market_prices = {"AAPL": 160.0}

        result = compute_underlying_exposure(
            positions, strategies, {1: "Test"}, market_prices, risk_factor=0.3
        )

        aapl = result["underlying_exposure"]["AAPL"]
        assert aapl["price_unavailable"] is False
        assert aapl["positions"][0]["price_unavailable"] is False

    def test_risk_factor_20pct(self):
        positions = [_pos(underlying="AAPL", strike=150.0, right="P")]
        strategies = [_strategy(underlying="AAPL")]
        market_prices = {"AAPL": 160.0}

        result = compute_underlying_exposure(
            positions, strategies, {1: "Test"}, market_prices, risk_factor=0.2
        )

        # margin_price = 160 * 0.8 = 128, loss = max(0, 150-128) = 22, loss*100 = 2200
        aapl = result["underlying_exposure"]["AAPL"]
        assert aapl["est_loss"] == 2200.0

    def test_multiple_accounts(self):
        positions = [
            _pos(underlying="AAPL", account_id=1),
            _pos(underlying="AAPL", account_id=2),
        ]
        strategies = [
            _strategy(underlying="AAPL", account_id=1),
            _strategy(underlying="AAPL", account_id=2),
        ]
        market_prices = {"AAPL": 160.0}

        result = compute_underlying_exposure(
            positions, strategies, {1: "Acct1", 2: "Acct2"}, market_prices, 0.3
        )

        assert result["total_accounts"] == 2
        assert result["total_positions"] == 2
