from sqlalchemy import Column, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    trade_date = Column(Text, nullable=False)
    symbol = Column(Text, nullable=False)
    underlying = Column(Text)
    expiry = Column(Text)
    strike = Column(Float)
    right = Column(Text)
    quantity = Column(Float, nullable=False)
    trade_price = Column(Float)
    proceeds = Column(Float)
    commission = Column(Float)
    net_cash = Column(Float)
    imported_at = Column(Text, nullable=False, default="CURRENT_TIMESTAMP")

    account = relationship("Account", backref="trades")

    __table_args__ = (
        Index("idx_trades_account", "account_id"),
        Index("idx_trades_symbol", "symbol"),
        Index("idx_trades_underlying", "underlying"),
        Index("idx_trades_date", "trade_date"),
    )
