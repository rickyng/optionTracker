from app.config import FX_RATES, get_fx_rate


class TestGetFxRate:
    def test_jpy_tokyo(self):
        assert get_fx_rate("1321.T") == 0.0067

    def test_jpy_tokyo_case_insensitive(self):
        assert get_fx_rate("1321.t") == 0.0067

    def test_hkd_hong_kong(self):
        assert get_fx_rate("0700.HK") == 0.13

    def test_usd_no_suffix(self):
        assert get_fx_rate("AAPL") == 1.0

    def test_usd_common_stocks(self):
        assert get_fx_rate("SPY") == 1.0
        assert get_fx_rate("MSFT") == 1.0

    def test_empty_string(self):
        assert get_fx_rate("") == 1.0

    def test_fx_rates_dict(self):
        assert ".T" in FX_RATES
        assert ".HK" in FX_RATES
        assert FX_RATES[".T"] == 0.0067
        assert FX_RATES[".HK"] == 0.13
