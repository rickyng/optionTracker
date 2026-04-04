from sqlalchemy import Column, ForeignKey, Index, Integer, Text

from app.database import Base


class StrategyLeg(Base):
    __tablename__ = "strategy_legs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, ForeignKey("detected_strategies.id", ondelete="CASCADE"), nullable=False)
    option_id = Column(Integer, ForeignKey("open_options.id", ondelete="CASCADE"), nullable=False)
    leg_role = Column(Text)

    __table_args__ = (
        Index("idx_strategy_legs_strategy", "strategy_id"),
        Index("idx_strategy_legs_option", "option_id"),
    )
