from sqlalchemy import Column, Text

from app.database import Base


class Metadata(Base):
    __tablename__ = "metadata"

    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False, default="CURRENT_TIMESTAMP")
