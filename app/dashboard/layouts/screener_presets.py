"""Strategy preset data for the CSP Screener.

Each preset defines recommended filter parameters for a volatility group.
Presets are filter templates only — they don't modify or filter the watchlist.
The ticker lists are reference indicators of stocks that typically fit each profile.
"""

STRATEGY_PRESETS = {
    "high_vol": {
        "label": "High Vol (Aggressive)",
        "tickers": ["TSLA", "NVDA", "PLTR", "U"],
        "filters": {
            "min_iv": 60,
            "min_delta": 0.15,
            "max_delta": 0.25,
            "min_dte": 14,
            "max_dte": 45,
            "min_otm": 15,
            "min_roc": 12,
            "max_capital": 50000,
        },
        "note": "Wide OTM buffer (15-25%) for 10-20%+ movers. IV Rank >60-70%.",
        "color": "#ff5252",
    },
    "med_high": {
        "label": "Medium-High Vol",
        "tickers": ["AVGO", "NFLX", "PYPL", "ADBE", "SAP"],
        "filters": {
            "min_iv": 55,
            "min_delta": 0.15,
            "max_delta": 0.28,
            "min_dte": 14,
            "max_dte": 45,
            "min_otm": 12,
            "min_roc": 12,
            "max_capital": 50000,
        },
        "note": "Good balance, elevated IV around earnings. OTM 12-20%.",
        "color": "#ffc107",
    },
    "stable_mega": {
        "label": "Stable Mega-Caps",
        "tickers": ["MSFT", "AMZN", "GOOG", "META", "V"],
        "filters": {
            "min_iv": 45,
            "min_delta": 0.20,
            "max_delta": 0.30,
            "min_dte": 14,
            "max_dte": 45,
            "min_otm": 8,
            "min_roc": 12,
            "max_capital": 50000,
        },
        "note": "Accept closer strikes for income. IV Rank >45-50%.",
        "color": "#448aff",
    },
    "defensive": {
        "label": "Defensive",
        "tickers": ["TSM", "UNH"],
        "filters": {
            "min_iv": 40,
            "min_delta": 0.20,
            "max_delta": 0.30,
            "min_dte": 14,
            "max_dte": 45,
            "min_otm": 8,
            "min_roc": 12,
            "max_capital": 50000,
        },
        "note": "Portfolio ballast, lower premiums. IV Rank >40%.",
        "color": "#00e676",
    },
}
