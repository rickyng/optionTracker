from pydantic_settings import BaseSettings

# FX rates: non-USD suffix → rate to convert to USD.
# Detect currency from the underlying symbol suffix (e.g. "1321.T" = Tokyo).
# Purely numeric symbols are assumed to be HK stocks (e.g. "1299" → HKD).
FX_RATES: dict[str, float] = {
    ".T": 0.0067,  # JPY → USD (Tokyo Stock Exchange)
    ".HK": 0.13,  # HKD → USD (Hong Kong Stock Exchange)
}


def get_fx_rate(underlying: str) -> float:
    """Return the FX rate to convert this underlying's currency to USD.

    Returns 1.0 for USD-denominated symbols.
    Purely numeric symbols (e.g. "1299") are treated as HK stocks.
    """
    # Check for explicit suffix
    for suffix, rate in FX_RATES.items():
        if underlying.upper().endswith(suffix.upper()):
            return rate
    # Purely numeric symbols are HK stocks
    if underlying.isdigit():
        return FX_RATES[".HK"]
    return 1.0


def get_market(underlying: str) -> str:
    """Return the market code for an underlying symbol: 'US', 'JP', or 'HK'."""
    if underlying.isdigit():
        return "HK"
    for suffix in FX_RATES:
        if underlying.upper().endswith(suffix.upper()):
            return "JP" if suffix == ".T" else "HK"
    return "US"


class Settings(BaseSettings):
    # Database — use db_url for Turso/libSQL, or db_path for local SQLite
    db_path: str = "~/.ibkr-options-analyzer/data.db"
    db_url: str = ""  # e.g. libsql://my-db-my-org.turso.io
    db_auth_token: str = ""

    # HTTP Client
    http_timeout: int = 30
    http_max_retries: int = 5
    http_retry_delay_ms: int = 2000

    # Flex Polling
    flex_poll_interval: int = 5
    flex_max_poll_duration: int = 300

    # Logging
    log_level: str = "INFO"

    # Price Fetching
    alphavantage_api_key: str = ""

    # yfinance Rate Limiting
    yfinance_delay_between_symbols: float = 2.0  # seconds between ticker.info calls
    yfinance_delay_between_chains: float = 1.5  # seconds between option_chain calls
    yfinance_ticker_delay: float = 5.0  # seconds between ticker scans
    yfinance_rate_limit_cooldown: float = 30.0  # seconds to pause after any 429

    # Dashboard Callbacks
    dashboard_api_timeout_short: int = 5  # CRUD operations
    dashboard_api_timeout_medium: int = 15  # Data fetches
    dashboard_api_timeout_long: int = 45  # Job polling
    dashboard_api_timeout_extended: int = 180  # Manual refresh

    model_config = {"env_prefix": "IBKR_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
