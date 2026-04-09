from sqlalchemy import Column, Float, Index, Text

from app.database import Base


class MarketPrice(Base):
    """Cached market prices for underlying symbols.

    Prices are fetched from Yahoo Finance/Alpha Vantage and stored here.
    Dashboard reads from this table (instant) instead of calling external APIs.
    """

    __tablename__ = "market_prices"

    symbol = Column(Text, primary_key=True)  # e.g. "AAPL"
    price = Column(Float, nullable=False)
    updated_at = Column(Text, nullable=False, default="CURRENT_TIMESTAMP")

    __table_args__ = (Index("idx_market_prices_updated", "updated_at"),)