from sqlalchemy import Column, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship

from app.database import Base


class DetectedStrategy(Base):
    __tablename__ = "detected_strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    strategy_type = Column(Text, nullable=False)
    underlying = Column(Text, nullable=False)
    expiry = Column(Text, nullable=False)
    leg_count = Column(Integer, nullable=False)
    net_premium = Column(Float)
    max_profit = Column(Float)
    max_loss = Column(Float)
    breakeven_price = Column(Float)
    confidence = Column(Float)
    detected_at = Column(Text, nullable=False, default="CURRENT_TIMESTAMP")

    account = relationship("Account", backref="strategies")
    legs = relationship("StrategyLeg", backref="strategy", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_strategies_account", "account_id"),
        Index("idx_strategies_underlying", "underlying"),
        Index("idx_strategies_type", "strategy_type"),
    )
