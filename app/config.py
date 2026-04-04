from pydantic_settings import BaseSettings

# FX rates: non-USD suffix → rate to convert to USD.
# Detect currency from the underlying symbol suffix (e.g. "1321.T" = Tokyo).
FX_RATES: dict[str, float] = {
    ".T": 0.0067,  # JPY → USD (Tokyo Stock Exchange)
    ".HK": 0.13,  # HKD → USD (Hong Kong Stock Exchange)
}


def get_fx_rate(underlying: str) -> float:
    """Return the FX rate to convert this underlying's currency to USD.

    Returns 1.0 for USD-denominated symbols.
    """
    for suffix, rate in FX_RATES.items():
        if underlying.upper().endswith(suffix.upper()):
            return rate
    return 1.0


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

    model_config = {"env_prefix": "IBKR_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
