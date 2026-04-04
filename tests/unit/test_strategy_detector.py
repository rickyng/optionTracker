from app.analysis.strategy_detector import detect_strategies
from app.schemas.position import Position


def _pos(
    id=1,
    account_id=1,
    underlying="AAPL",
    expiry="2099-03-21",
    strike=150.0,
    right="P",
    quantity=-1.0,
    entry_premium=3.50,
) -> Position:
    return Position(
        id=id,
        account_id=account_id,
        account_name="Test",
        symbol=f"AAPL  250321{right}00{int(strike * 1000):08d}",
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        quantity=quantity,
        mark_price=2.0,
        entry_premium=entry_premium,
        is_manual=False,
    )


class TestDetectStrategies:
    def test_naked_short_put(self):
        positions = [_pos(right="P", quantity=-2)]
        strategies = detect_strategies(positions)
        assert len(strategies) == 1
        assert strategies[0].type.value == "naked_short_put"

    def test_naked_short_call(self):
        positions = [_pos(right="C", quantity=-1)]
        strategies = detect_strategies(positions)
        assert len(strategies) == 1
        assert strategies[0].type.value == "naked_short_call"

    def test_bull_put_spread(self):
        positions = [
            _pos(id=1, strike=150, right="P", quantity=-1),
            _pos(id=2, strike=140, right="P", quantity=1),
        ]
        strategies = detect_strategies(positions)
        assert len(strategies) == 1
        assert strategies[0].type.value == "bull_put_spread"

    def test_bear_call_spread(self):
        positions = [
            _pos(id=1, strike=150, right="C", quantity=-1),
            _pos(id=2, strike=160, right="C", quantity=1),
        ]
        strategies = detect_strategies(positions)
        assert len(strategies) == 1
        assert strategies[0].type.value == "bear_call_spread"

    def test_iron_condor(self):
        positions = [
            _pos(id=1, strike=145, right="P", quantity=-1),
            _pos(id=2, strike=140, right="P", quantity=1),
            _pos(id=3, strike=155, right="C", quantity=-1),
            _pos(id=4, strike=160, right="C", quantity=1),
        ]
        strategies = detect_strategies(positions)
        assert len(strategies) == 1
        assert strategies[0].type.value == "iron_condor"

    def test_straddle(self):
        positions = [
            _pos(id=1, strike=150, right="P", quantity=-1),
            _pos(id=2, strike=150, right="C", quantity=-1),
        ]
        strategies = detect_strategies(positions)
        assert len(strategies) == 1
        assert strategies[0].type.value == "straddle"

    def test_strangle(self):
        positions = [
            _pos(id=1, strike=145, right="P", quantity=-1),
            _pos(id=2, strike=155, right="C", quantity=-1),
        ]
        strategies = detect_strategies(positions)
        assert len(strategies) == 1
        assert strategies[0].type.value == "strangle"

    def test_groups_by_underlying_expiry(self):
        positions = [
            _pos(id=1, underlying="AAPL", strike=150, right="P", quantity=-1),
            _pos(id=2, underlying="SPY", strike=500, right="P", quantity=-2),
        ]
        strategies = detect_strategies(positions)
        assert len(strategies) == 2

    def test_empty_positions(self):
        assert detect_strategies([]) == []
