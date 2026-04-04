import csv
import io
import logging

from app.parsers.option_symbol import OptionParseResult, is_option_symbol, parse_option_symbol
from app.schemas.flex import OpenPositionRecord, TradeRecord

logger = logging.getLogger(__name__)

# CSV column mappings
TRADE_COLUMNS = {
    "ClientAccountID": "account_id",
    "TradeDate": "trade_date",
    "Symbol": "symbol",
    "Description": "description",
    "UnderlyingSymbol": "underlying_symbol",
    "Expiry": "expiry",
    "Strike": "strike",
    "Put/Call": "put_call",
    "Quantity": "quantity",
    "TradePrice": "trade_price",
    "Proceeds": "proceeds",
    "Commission": "commission",
    "NetCash": "net_cash",
    "AssetClass": "asset_class",
}

OPEN_POSITION_COLUMNS = {
    "ClientAccountID": "account_id",
    "Symbol": "symbol",
    "Description": "description",
    "UnderlyingSymbol": "underlying_symbol",
    "Expiry": "expiry",
    "Strike": "strike",
    "Put/Call": "put_call",
    "Quantity": "quantity",
    "MarkPrice": "mark_price",
    "PositionValue": "position_value",
    "OpenPrice": "open_price",
    "CostBasisPrice": "cost_basis_price",
    "CostBasisMoney": "cost_basis_money",
    "FifoPnlUnrealized": "unrealized_pnl",
    "AssetClass": "asset_class",
    "ReportDate": "report_date",
    "Multiplier": "multiplier",
}


def _safe_float(value: str | None, default: float = 0.0) -> float:
    if not value:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _row_to_dict(row: dict, column_map: dict[str, str]) -> dict:
    """Map CSV column names to field names, converting types."""
    result = {}
    for csv_col, field in column_map.items():
        val = row.get(csv_col, "")
        result[field] = val if isinstance(val, str) else str(val)
    return result


def _should_skip_trade(row: dict) -> bool:
    """Apply filtering rules for trade rows."""
    if row.get("AssetClass", "").upper() != "OPT":
        return True
    if row.get("LevelOfDetail", "") == "EXECUTION":
        return True
    return abs(_safe_float(row.get("Quantity", "0"))) > 10000


def _should_skip_position(row: dict, skip_expired: bool = True) -> bool:
    """Apply filtering rules for open position rows."""
    if row.get("AssetClass", "").upper() != "OPT":
        return True
    if abs(_safe_float(row.get("Quantity", "0"))) > 10000:
        return True
    if skip_expired:
        symbol = row.get("Symbol", "")
        if is_option_symbol(symbol):
            parsed = parse_option_symbol(symbol)
            if parsed and _is_date_expired(parsed.expiry):
                return True
    return False


def _is_date_expired(date_str: str) -> bool:
    from datetime import date

    try:
        parts = date_str.strip().split("-")
        if len(parts) == 3:
            exp = date(int(parts[0]), int(parts[1]), int(parts[2]))
            return exp <= date.today()
    except (ValueError, IndexError):
        pass
    return False


def _enrich_from_option_details(mapped: dict, details: OptionParseResult) -> None:
    """Fill in missing/invalid fields from a parsed option symbol."""
    if not mapped.get("underlying_symbol"):
        mapped["underlying_symbol"] = details.underlying
    if not mapped.get("expiry"):
        mapped["expiry"] = details.expiry
    if not mapped.get("strike") or _safe_float(mapped.get("strike")) == 0.0:
        mapped["strike"] = str(details.strike)
    if mapped.get("put_call", "") not in ("C", "P"):
        mapped["put_call"] = details.right


def _has_trade_columns(fieldnames: list[str] | None) -> bool:
    """Check whether the CSV contains trade-specific columns."""
    if not fieldnames:
        return False
    required = {"TradeDate", "TradePrice", "Proceeds", "Commission", "NetCash"}
    return required.issubset(set(fieldnames))


def _split_csv_sections(csv_content: str) -> dict[str, str]:
    """Split a multi-section IBKR Flex CSV into named sections.

    IBKR Flex reports can contain multiple sections (OpenPositions, Trades, etc.)
    each starting with their own header row. Returns a dict mapping a section
    identifier (based on the header's distinctive columns) to its CSV content
    (header + data rows).
    """
    lines = csv_content.split("\n")
    sections: list[tuple[list[str], list[str]]] = []  # (header_lines, data_lines)
    current_header: list[str] = []
    current_data: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Detect a header row: starts with ClientAccountID (common first column)
        if stripped.startswith('"ClientAccountID"') or stripped.startswith("ClientAccountID"):
            # Save previous section if any
            if current_header:
                sections.append((current_header, current_data))
            current_header = [stripped]
            current_data = []
        elif current_header:
            current_data.append(stripped)

    # Don't forget the last section
    if current_header:
        sections.append((current_header, current_data))

    result: dict[str, str] = {}
    for header_lines, data_lines in sections:
        header_str = header_lines[0]
        # Identify section by its distinctive columns
        if "OpenPrice" in header_str or "MarkPrice" in header_str:
            key = "positions"
        elif "TradePrice" in header_str or "TradeDate" in header_str:
            key = "trades"
        else:
            key = f"unknown_{len(result)}"
        result[key] = "\n".join(header_lines + data_lines)

    return result


def parse_trades_csv(csv_content: str) -> list[TradeRecord]:
    """Parse trade rows from IBKR Flex CSV content."""
    sections = _split_csv_sections(csv_content)
    trade_csv = sections.get("trades", "")
    if not trade_csv:
        logger.info("No trade section found in CSV — skipping trade parsing")
        return []
    reader = csv.DictReader(io.StringIO(trade_csv))
    if not _has_trade_columns(reader.fieldnames):
        logger.info("No trade-specific columns found — skipping trade parsing")
        return []
    records = []
    for row in reader:
        if _should_skip_trade(row):
            continue
        mapped = _row_to_dict(row, TRADE_COLUMNS)
        symbol = mapped.get("symbol", "")
        option_details = parse_option_symbol(symbol) if is_option_symbol(symbol) else None
        if option_details:
            _enrich_from_option_details(mapped, option_details)
        records.append(
            TradeRecord(
                account_id=mapped.get("account_id", ""),
                trade_date=mapped.get("trade_date", ""),
                symbol=symbol,
                description=mapped.get("description", ""),
                underlying_symbol=mapped.get("underlying_symbol", ""),
                expiry=mapped.get("expiry", ""),
                strike=_safe_float(mapped.get("strike")),
                put_call=mapped.get("put_call", ""),
                quantity=_safe_float(mapped.get("quantity")),
                trade_price=_safe_float(mapped.get("trade_price")),
                proceeds=_safe_float(mapped.get("proceeds")),
                commission=_safe_float(mapped.get("commission")),
                net_cash=_safe_float(mapped.get("net_cash")),
                asset_class=mapped.get("asset_class", ""),
                option_details=option_details,
            )
        )
    return records


def parse_open_positions_csv(csv_content: str, skip_expired: bool = True) -> list[OpenPositionRecord]:
    """Parse open position rows from IBKR Flex CSV content."""
    sections = _split_csv_sections(csv_content)
    positions_csv = sections.get("positions", csv_content)
    reader = csv.DictReader(io.StringIO(positions_csv))
    if reader.fieldnames:
        logger.info("OpenPosition CSV columns: %s", reader.fieldnames)
        missing = set(OPEN_POSITION_COLUMNS.keys()) - set(reader.fieldnames)
        if missing:
            logger.warning("OpenPosition CSV missing expected columns: %s", missing)
    records = []
    for row in reader:
        if _should_skip_position(row, skip_expired):
            continue
        mapped = _row_to_dict(row, OPEN_POSITION_COLUMNS)
        symbol = mapped.get("symbol", "")
        option_details = parse_option_symbol(symbol) if is_option_symbol(symbol) else None
        if option_details:
            _enrich_from_option_details(mapped, option_details)
        rec = OpenPositionRecord(
            account_id=mapped.get("account_id", ""),
            symbol=symbol,
            description=mapped.get("description", ""),
            underlying_symbol=mapped.get("underlying_symbol", ""),
            expiry=mapped.get("expiry", ""),
            strike=_safe_float(mapped.get("strike")),
            put_call=mapped.get("put_call", ""),
            quantity=_safe_float(mapped.get("quantity")),
            multiplier=_safe_float(mapped.get("multiplier"), default=100.0),
            mark_price=_safe_float(mapped.get("mark_price")),
            position_value=_safe_float(mapped.get("position_value")),
            open_price=_safe_float(mapped.get("open_price")),
            cost_basis_price=_safe_float(mapped.get("cost_basis_price")),
            cost_basis_money=_safe_float(mapped.get("cost_basis_money")),
            unrealized_pnl=_safe_float(mapped.get("unrealized_pnl")),
            asset_class=mapped.get("asset_class", ""),
            report_date=mapped.get("report_date", ""),
            option_details=option_details,
        )
        if not _validate_position_record(rec, row):
            continue
        records.append(rec)
    return records


def _validate_position_record(rec: OpenPositionRecord, raw_row: dict) -> bool:
    """Validate a parsed position record has sensible field values.

    Returns True if valid, False if the record should be skipped.
    Catches column-mismatch issues where values end up in wrong fields.
    """
    errors = []
    if rec.put_call not in ("C", "P"):
        errors.append(f"put_call={rec.put_call!r}")
    if not rec.underlying_symbol:
        errors.append("underlying_symbol is empty")
    if not rec.expiry:
        errors.append("expiry is empty")
    if errors:
        logger.warning(
            "Skipping invalid position record (likely column mismatch): symbol=%s %s | raw keys present: %s",
            rec.symbol,
            ", ".join(errors),
            list(raw_row.keys()),
        )
        return False
    return True
