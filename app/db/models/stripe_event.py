from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint, text
from app.db.database import Base


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    id = Column(String, primary_key=True, index=True)
    stripe_event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    processed_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)

    __table_args__ = (
        UniqueConstraint("stripe_event_id", name="uq_stripe_event_id"),
    )
