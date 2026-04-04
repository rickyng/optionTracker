from app.parsers.option_symbol import is_expired, is_option_symbol, normalize_underlying, parse_option_symbol


class TestIsOptionSymbol:
    def test_standard_option(self):
        assert is_option_symbol("AAPL  250321P00150000") is True

    def test_compact_option(self):
        assert is_option_symbol("AAPL250321P150") is True

    def test_stock_symbol(self):
        assert is_option_symbol("AAPL") is False

    def test_empty_string(self):
        assert is_option_symbol("") is False


class TestParseOptionSymbol:
    def test_format1_spaced_8digit_strike(self):
        result = parse_option_symbol("AAPL  250321P00150000")
        assert result is not None
        assert result.underlying == "AAPL"
        assert result.expiry == "2025-03-21"
        assert result.strike == 150.0
        assert result.right == "P"

    def test_format2_compact_decimal_strike(self):
        result = parse_option_symbol("AAPL250321P150")
        assert result is not None
        assert result.underlying == "AAPL"
        assert result.expiry == "2025-03-21"
        assert result.strike == 150.0
        assert result.right == "P"

    def test_call_option(self):
        result = parse_option_symbol("SPY  250620C00550000")
        assert result is not None
        assert result.right == "C"
        assert result.strike == 550.0

    def test_not_an_option(self):
        assert parse_option_symbol("AAPL") is None

    def test_whitespace_handling(self):
        result = parse_option_symbol("  AAPL  250321P00150000  ")
        assert result is not None
        assert result.underlying == "AAPL"

    def test_small_strike(self):
        result = parse_option_symbol("T  250321P00025000")
        assert result is not None
        assert result.strike == 25.0

    def test_compact_with_decimal(self):
        result = parse_option_symbol("MSFT250321C420.5")
        assert result is not None
        assert result.strike == 420.5


class TestNormalizeUnderlying:
    def test_brkb_mapping(self):
        assert normalize_underlying("BRKB") == "BRK-B"

    def test_normal_symbol(self):
        assert normalize_underlying("AAPL") == "AAPL"


class TestIsExpired:
    def test_past_date(self):
        assert is_expired("2020-01-01") is True

    def test_future_date(self):
        assert is_expired("2099-12-31") is False
