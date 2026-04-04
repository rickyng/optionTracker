from app.parsers.csv_parser import parse_open_positions_csv, parse_trades_csv

TRADE_CSV = """ClientAccountID,TradeDate,Symbol,Description,UnderlyingSymbol,Expiry,Strike,Put/Call,Quantity,TradePrice,Proceeds,Commission,NetCash,AssetClass,LevelOfDetail
U12345,2025-01-15,AAPL  250321P00150000,AAPL 21MAR25 150 P,AAPL,2025-03-21,150,P,-2,3.50,700.00,-1.00,699.00,OPT,TRADE
U12345,2025-01-15,SPY,AAPL STOCK,,OPT,,,,0,0,0,0,STK,TRADE
U12345,2025-01-15,AAPL  250321C00150000,AAPL 21MAR25 150 C,AAPL,2025-03-21,150,C,1,2.10,-210.00,-0.50,-210.50,OPT,EXECUTION"""

OPEN_POS_CSV = """ClientAccountID,Symbol,Description,UnderlyingSymbol,Expiry,Strike,Put/Call,Quantity,MarkPrice,PositionValue,OpenPrice,CostBasisPrice,CostBasisMoney,FifoPnlUnrealized,AssetClass,ReportDate
U12345,AAPL  250321P00150000,AAPL 21MAR25 150 P,AAPL,2025-03-21,150,P,-2,2.80,560.00,3.50,350.00,700.00,140.00,OPT,2025-02-01
U12345,AAPL,AAPL STOCK,AAPL,,,,100,185.00,18500.00,170.00,17000.00,17000.00,1500.00,STK,2025-02-01"""


class TestParseTradesCsv:
    def test_parses_option_trades(self):
        records = parse_trades_csv(TRADE_CSV)
        assert len(records) == 1  # STK and EXECUTION rows filtered
        r = records[0]
        assert r.account_id == "U12345"
        assert r.underlying_symbol == "AAPL"
        assert r.quantity == -2.0
        assert r.put_call == "P"
        assert r.option_details is not None
        assert r.option_details.strike == 150.0

    def test_filters_non_opt(self):
        records = parse_trades_csv(TRADE_CSV)
        underlyings = [r.underlying_symbol for r in records]
        assert "SPY" not in underlyings

    def test_filters_execution_level(self):
        records = parse_trades_csv(TRADE_CSV)
        # The C execution row should be filtered
        calls = [r for r in records if r.put_call == "C"]
        assert len(calls) == 0

    def test_empty_csv(self):
        records = parse_trades_csv("")
        assert records == []


class TestParseOpenPositionsCsv:
    def test_parses_option_positions(self):
        records = parse_open_positions_csv(OPEN_POS_CSV, skip_expired=False)
        assert len(records) == 1  # STK row filtered
        r = records[0]
        assert r.account_id == "U12345"
        assert r.quantity == -2.0
        assert r.mark_price == 2.80
        assert r.option_details is not None
        assert r.option_details.right == "P"

    def test_filters_non_opt(self):
        records = parse_open_positions_csv(OPEN_POS_CSV, skip_expired=False)
        symbols = [r.symbol for r in records]
        assert "AAPL" not in symbols  # stock row filtered

    def test_empty_csv(self):
        records = parse_open_positions_csv("")
        assert records == []
