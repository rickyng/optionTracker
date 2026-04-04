import pytest

from app.analysis.risk_calculator import calculate_risk
from app.schemas.position import Position
from app.schemas.strategy import StrategyType


def _make_position(strike=150.0, right="P", quantity=-1.0, entry_premium=3.50, expiry="2099-12-20") -> Position:
    return Position(
        id=1,
        account_id=1,
        account_name="Test",
        symbol="TEST",
        underlying="TEST",
        expiry=expiry,
        strike=strike,
        right=right,
        quantity=quantity,
        mark_price=2.0,
        entry_premium=entry_premium,
        is_manual=False,
    )


class TestNakedShortPut:
    def test_basic(self):
        pos = _make_position(strike=150, right="P", quantity=-2, entry_premium=3.50)
        risk = calculate_risk(StrategyType.NAKED_SHORT_PUT, [pos])
        assert risk.max_profit == 2 * 3.50 * 100  # 700
        assert risk.breakeven_price == 150 - 3.50
        assert risk.max_loss == (150 - 3.50) * 100 * 2
        assert risk.risk_level == "HIGH"


class TestNakedShortCall:
    def test_basic(self):
        pos = _make_position(strike=200, right="C", quantity=-1, entry_premium=5.0)
        risk = calculate_risk(StrategyType.NAKED_SHORT_CALL, [pos])
        assert risk.max_profit == 500.0
        assert risk.breakeven_price == 205.0
        assert risk.max_loss == float("inf")
        assert risk.risk_level == "HIGH"


class TestBullPutSpread:
    def test_basic(self):
        short = _make_position(strike=150, right="P", quantity=-1, entry_premium=5.0)
        long = _make_position(strike=140, right="P", quantity=1, entry_premium=2.0)
        risk = calculate_risk(StrategyType.BULL_PUT_SPREAD, [short, long])
        assert risk.max_profit == 300.0  # 500 - 200
        assert risk.risk_level == "DEFINED"
        assert risk.max_loss > 0


class TestBearCallSpread:
    def test_basic(self):
        short = _make_position(strike=150, right="C", quantity=-1, entry_premium=4.0)
        long = _make_position(strike=160, right="C", quantity=1, entry_premium=1.50)
        risk = calculate_risk(StrategyType.BEAR_CALL_SPREAD, [short, long])
        assert risk.max_profit == 250.0  # 400 - 150
        assert risk.risk_level == "DEFINED"


class TestIronCondor:
    def test_basic(self):
        sp = _make_position(strike=145, right="P", quantity=-1, entry_premium=4.0)
        lp = _make_position(strike=140, right="P", quantity=1, entry_premium=2.0)
        sc = _make_position(strike=155, right="C", quantity=-1, entry_premium=3.50)
        lc = _make_position(strike=160, right="C", quantity=1, entry_premium=1.50)
        risk = calculate_risk(StrategyType.IRON_CONDOR, [sp, lp, sc, lc])
        assert risk.max_profit == 400.0  # 400+350 - 200-150
        assert risk.risk_level == "DEFINED"
        assert risk.breakeven_price_2 > 0


class TestStraddle:
    def test_basic(self):
        put = _make_position(strike=150, right="P", quantity=-1, entry_premium=5.0)
        call = _make_position(strike=150, right="C", quantity=-1, entry_premium=4.0)
        risk = calculate_risk(StrategyType.STRADDLE, [put, call])
        assert risk.max_loss == 900.0  # 500 + 400
        assert risk.risk_level == "MEDIUM"


class TestMultiplierNot100:
    """Verify that non-standard multipliers (e.g. Japanese 1-share contracts) work."""

    def _make_jp_position(self, strike=368.5, right="P", quantity=-10, entry_premium=11.0081, expiry="2099-12-20"):
        return Position(
            id=1,
            account_id=1,
            account_name="Test",
            symbol="1321.T",
            underlying="1321.T",
            expiry=expiry,
            strike=strike,
            right=right,
            quantity=quantity,
            mark_price=5.0,
            entry_premium=entry_premium,
            multiplier=1,
            is_manual=False,
        )

    def test_naked_short_put_multiplier_1(self):
        pos = self._make_jp_position(strike=368.5, quantity=-10, entry_premium=11.0081)
        risk = calculate_risk(StrategyType.NAKED_SHORT_PUT, [pos])
        # max_profit = 10 * 11.0081 * 1 = 110.081 (not * 100)
        assert risk.max_profit == pytest.approx(110.081)
        # breakeven = 368.5 - 11.0081 = 357.4919
        assert risk.breakeven_price == pytest.approx(357.4919)
        # max_loss = 357.4919 * 1 * 10 = 3574.919 (not * 100)
        assert risk.max_loss == pytest.approx(3574.919)

    def test_bull_put_spread_multiplier_1(self):
        short = self._make_jp_position(strike=375.2, quantity=-9, entry_premium=13.601)
        long = self._make_jp_position(strike=368.5, quantity=1, entry_premium=11.0081)
        risk = calculate_risk(StrategyType.BULL_PUT_SPREAD, [short, long])
        # short_premium = 9 * 13.601 * 1 = 122.409
        # long_premium = 1 * 11.0081 * 1 = 11.0081
        # net_premium = 111.4009
        assert risk.max_profit == pytest.approx(111.4009)
