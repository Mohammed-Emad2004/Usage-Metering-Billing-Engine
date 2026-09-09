from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import relationship
from app.db.database import Base


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_type = Column(String, nullable=False) # api_calls, ai_tokens
    quantity = Column(Integer, nullable=False)
    idempotency_key = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False)

    # Token sub-category breakdown (only meaningful for ai_tokens; zero for api_calls)
    input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    cached_input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    output_tokens = Column(Integer, nullable=False, server_default=text("0"))
    reasoning_tokens = Column(Integer, nullable=False, server_default=text("0"))

    tenant = relationship("Tenant", backref="usage_events")

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_idempotency_key"),
    )
