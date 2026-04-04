from sqlalchemy import CheckConstraint, Column, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship

from app.database import Base


class OpenOption(Base):
    __tablename__ = "open_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(Text, nullable=False)
    underlying = Column(Text, nullable=False)
    expiry = Column(Text, nullable=False)
    strike = Column(Float, nullable=False)
    right = Column(Text, nullable=False)
    quantity = Column(Float, nullable=False)
    multiplier = Column(Integer, nullable=False, default=100)
    mark_price = Column(Float)
    entry_premium = Column(Float)
    current_value = Column(Float)
    is_manual = Column(Integer, nullable=False, default=0)
    notes = Column(Text)
    created_at = Column(Text, nullable=False, default="CURRENT_TIMESTAMP")
    updated_at = Column(Text, nullable=False, default="CURRENT_TIMESTAMP")

    account = relationship("Account", backref="open_options")
    strategy_legs = relationship("StrategyLeg", backref="option", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("right IN ('C', 'P')", name="ck_open_options_right"),
        Index("idx_open_options_account", "account_id"),
        Index("idx_open_options_underlying", "underlying"),
        Index("idx_open_options_expiry", "expiry"),
        Index("idx_open_options_symbol", "symbol"),
        Index("idx_open_options_acct_underlying_expiry", "account_id", "underlying", "expiry"),
    )
