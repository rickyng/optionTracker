import pytest

from app.analysis.option_greeks import (
    black_scholes_put_delta,
    calc_ann_roc,
    calc_otm_pct,
    calc_rating,
    is_strong_fundamentals,
    passes_filters,
)


class TestBlackScholesPutDelta:
    def test_atm_put_delta_near_negative_50(self):
        delta = black_scholes_put_delta(s=100, k=100, t=30 / 365, r=0.05, sigma=0.30)
        assert -0.55 < delta < -0.45

    def test_deep_otm_put_delta_near_zero(self):
        delta = black_scholes_put_delta(s=100, k=80, t=30 / 365, r=0.05, sigma=0.30)
        assert -0.10 < delta < 0

    def test_deep_itm_put_delta_near_negative_1(self):
        delta = black_scholes_put_delta(s=100, k=120, t=30 / 365, r=0.05, sigma=0.30)
        assert -1.0 < delta < -0.85

    def test_zero_dte_returns_boundary(self):
        delta_itm = black_scholes_put_delta(s=100, k=110, t=1 / 365, r=0.05, sigma=0.30)
        assert delta_itm < -0.9
        delta_otm = black_scholes_put_delta(s=100, k=90, t=1 / 365, r=0.05, sigma=0.30)
        assert delta_otm > -0.1


class TestCalcOtmPct:
    def test_otm_put(self):
        assert calc_otm_pct(price=100, strike=90) == pytest.approx(10.0)

    def test_atm(self):
        assert calc_otm_pct(price=100, strike=100) == pytest.approx(0.0)

    def test_itm_negative(self):
        assert calc_otm_pct(price=100, strike=110) == pytest.approx(-10.0)


class TestCalcAnnRoc:
    def test_basic(self):
        roc = calc_ann_roc(premium=3.0, strike=150.0, dte=30)
        assert roc == pytest.approx(24.33, rel=0.01)

    def test_zero_dte_returns_zero(self):
        assert calc_ann_roc(premium=3.0, strike=150.0, dte=0) == 0.0


class TestIsStrongFundamentals:
    def test_strong(self):
        assert is_strong_fundamentals(pe_ratio=25.0, profit_margin=20.0, beta=1.2) is True

    def test_negative_pe(self):
        assert is_strong_fundamentals(pe_ratio=-5.0, profit_margin=20.0, beta=1.2) is False

    def test_low_margin(self):
        assert is_strong_fundamentals(pe_ratio=25.0, profit_margin=5.0, beta=1.2) is False

    def test_high_beta(self):
        assert is_strong_fundamentals(pe_ratio=25.0, profit_margin=20.0, beta=2.0) is False

    def test_none_values(self):
        assert is_strong_fundamentals(pe_ratio=None, profit_margin=20.0, beta=1.2) is False


class TestCalcRating:
    def test_strong_5_stars(self):
        score, label = calc_rating(iv=0.65, delta=0.25, dte=35, ann_roc=25.0, strong_fundamentals=True)
        assert score == 5
        assert label == "STRONG"

    def test_good_4_stars(self):
        score, label = calc_rating(iv=0.45, delta=0.25, dte=25, ann_roc=12.0, strong_fundamentals=False)
        assert score == 4
        assert label == "GOOD"

    def test_ok_3_stars(self):
        score, label = calc_rating(iv=0.45, delta=0.25, dte=25, ann_roc=10.0, strong_fundamentals=False)
        assert score == 3
        assert label == "OK"

    def test_low_iv_penalty(self):
        score, label = calc_rating(iv=0.20, delta=0.25, dte=35, ann_roc=15.0, strong_fundamentals=False)
        assert label == "GOOD"

    def test_outside_delta_penalty(self):
        score, label = calc_rating(iv=0.45, delta=0.10, dte=35, ann_roc=15.0, strong_fundamentals=False)
        assert label == "OK"

    def test_poor_1_star(self):
        # iv<0.30: -1, delta>0.35: -1, dte outside range: 0, ann_roc<12: 0 = -2 → clamped to 1
        score, label = calc_rating(iv=0.10, delta=0.40, dte=10, ann_roc=5.0, strong_fundamentals=False)
        assert score == 1
        assert label == "POOR"

    def test_fair_2_stars(self):
        # iv<0.30: -1, delta 0.17 (no bonus/penalty): 0, dte 35: +2, ann_roc 15: +1 = 2
        score, label = calc_rating(iv=0.10, delta=0.17, dte=35, ann_roc=15.0, strong_fundamentals=False)
        assert score == 2
        assert label == "FAIR"


class TestPassesFilters:
    def test_passes_all(self):
        assert (
            passes_filters(
                iv=0.40,
                delta=0.25,
                dte=30,
                otm_pct=8.0,
                ann_roc=15.0,
                capital=30000,
                max_capital=50000,
                min_iv=0.30,
                min_delta=0.15,
                max_delta=0.35,
                min_dte=21,
                max_dte=45,
                min_otm_pct=5.0,
                min_ann_roc=12.0,
            )
            is True
        )

    def test_fails_iv(self):
        assert (
            passes_filters(
                iv=0.20,
                delta=0.25,
                dte=30,
                otm_pct=8.0,
                ann_roc=15.0,
                capital=30000,
                max_capital=50000,
                min_iv=0.30,
                min_delta=0.15,
                max_delta=0.35,
                min_dte=21,
                max_dte=45,
                min_otm_pct=5.0,
                min_ann_roc=12.0,
            )
            is False
        )

    def test_fails_delta_range(self):
        assert (
            passes_filters(
                iv=0.40,
                delta=0.40,
                dte=30,
                otm_pct=8.0,
                ann_roc=15.0,
                capital=30000,
                max_capital=50000,
                min_iv=0.30,
                min_delta=0.15,
                max_delta=0.35,
                min_dte=21,
                max_dte=45,
                min_otm_pct=5.0,
                min_ann_roc=12.0,
            )
            is False
        )

    def test_fails_capital(self):
        assert (
            passes_filters(
                iv=0.40,
                delta=0.25,
                dte=30,
                otm_pct=8.0,
                ann_roc=15.0,
                capital=60000,
                max_capital=50000,
                min_iv=0.30,
                min_delta=0.15,
                max_delta=0.35,
                min_dte=21,
                max_dte=45,
                min_otm_pct=5.0,
                min_ann_roc=12.0,
            )
            is False
        )
