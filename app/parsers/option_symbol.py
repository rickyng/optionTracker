import re
from datetime import date

from app.schemas.option import OptionParseResult

# Format 1: "AAPL  250321P00150000" (spaces + 8-digit strike)
FMT1_RE = re.compile(r"^([A-Z]+)\s+(\d{6})([CP])(\d{8})$")
# Format 2: "AAPL250321P150" (compact + decimal strike)
FMT2_RE = re.compile(r"^([A-Z]+)\s?(\d{6})([CP])([\d.]+)$")

SYMBOL_MAPPING = {
    "BRKB": "BRK-B",
    "BRKA": "BRK-A",
    "BRK.B": "BRK-B",
    "BRK.A": "BRK-A",
}


def is_option_symbol(symbol: str) -> bool:
    return bool(re.search(r"\d{6}[CP]", symbol))


def parse_option_symbol(symbol: str) -> OptionParseResult | None:
    """Parse an IBKR option symbol into its components.

    Returns None if the symbol is not a recognized option format.
    """
    symbol = symbol.strip()

    for pattern in [FMT1_RE, FMT2_RE]:
        m = pattern.match(symbol)
        if m:
            raw_underlying, date_str, right, strike_str = m.groups()
            underlying = SYMBOL_MAPPING.get(raw_underlying, raw_underlying)
            expiry = _convert_date(date_str)
            strike = float(strike_str) / 1000 if len(strike_str) == 8 else float(strike_str)
            return OptionParseResult(
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                right=right,
                original_symbol=symbol,
            )
    return None


def _convert_date(yy_mm_dd: str) -> str:
    """Convert YYMMDD to YYYY-MM-DD."""
    year = 2000 + int(yy_mm_dd[:2])
    month = int(yy_mm_dd[2:4])
    day = int(yy_mm_dd[4:6])
    return date(year, month, day).isoformat()


def is_expired(expiry: str) -> bool:
    """Check if an expiry date (YYYY-MM-DD) is today or earlier."""
    return expiry <= date.today().isoformat()


def normalize_underlying(symbol: str) -> str:
    """Apply symbol mapping for display/lookup purposes."""
    return SYMBOL_MAPPING.get(symbol, symbol)
