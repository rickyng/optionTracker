from sqlalchemy import Column, Index, Text

from app.database import Base


class EarningsDate(Base):
    """Cached upcoming earnings dates for underlying symbols.

    Fetched from Yahoo Finance via yfinance and stored here.
    Dashboard reads from this table to show earnings before expiry.
    """

    __tablename__ = "earnings_dates"

    symbol = Column(Text, primary_key=True)  # e.g. "AAPL"
    earnings_date = Column(Text)  # ISO date string "2025-04-30", nullable if none upcoming
    updated_at = Column(Text, nullable=False, default="CURRENT_TIMESTAMP")

    __table_args__ = (Index("idx_earnings_dates_updated", "updated_at"),)
