from sqlalchemy import Column, String, Integer, DateTime, text
from app.db.database import Base


class Plan(Base):
    __tablename__ = "plans"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    api_call_limit = Column(Integer, nullable=False)
    ai_token_limit = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
