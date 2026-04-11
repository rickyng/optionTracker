"""SQLAlchemy models for the CSP Screener watchlist and cached results."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String

from app.database import Base


class ScreenerWatchlist(Base):
    """Per-user watchlist of ticker symbols for CSP screening."""

    __tablename__ = "screener_watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_sub = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (Index("idx_watchlist_user_symbol", "user_sub", "symbol", unique=True),)


class ScreenerResult(Base):
    """Cached scan results — one row per passing put opportunity."""

    __tablename__ = "screener_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_sub = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    strike = Column(Float, nullable=False)
    expiry = Column(String, nullable=False)
    dte = Column(Integer, nullable=False)
    bid = Column(Float, nullable=False)
    mid = Column(Float, nullable=False)
    iv = Column(Float, nullable=False)
    delta = Column(Float, nullable=False)
    otm_pct = Column(Float, nullable=False)
    ann_roc_pct = Column(Float, nullable=False)
    capital_required = Column(Float, nullable=False)
    pe_ratio = Column(Float, nullable=True)
    beta = Column(Float, nullable=True)
    profit_margin = Column(Float, nullable=True)
    revenue_growth = Column(Float, nullable=True)
    strong_fundamentals = Column(Boolean, default=False)
    rating = Column(Integer, nullable=False)
    rating_label = Column(String, nullable=False)
    scanned_at = Column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (Index("idx_screener_results_user_scanned", "user_sub", "scanned_at"),)
