from sqlalchemy import Column, DateTime, Integer, Text, func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    google_sub = Column(Text, nullable=False, unique=True)
    email = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False, default="")
    picture = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
