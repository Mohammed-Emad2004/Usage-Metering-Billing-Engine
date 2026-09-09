from sqlalchemy.orm import Session
from app.db.models.tenant import Tenant
from app.db.models.plan import Plan
from app.db.models.subscription import Subscription
from app.db.models.usage_event import UsageEvent
from sqlalchemy import func
from datetime import datetime, timezone


class TenantRepository:
    @staticmethod
    def get_by_id(db: Session, tenant_id: str) -> Tenant | None:
        return db.query(Tenant).filter(Tenant.id == tenant_id).first()


class SubscriptionRepository:
    @staticmethod
    def get_by_tenant_id(db: Session, tenant_id: str) -> Subscription | None:
        return db.query(Subscription).filter(Subscription.tenant_id == tenant_id).first()


class UsageRepository:
    @staticmethod
    def create(
        db: Session, event_id: str, tenant_id: str, usage_type: str,
        quantity: int, idempotency_key: str,
        input_tokens: int = 0, cached_input_tokens: int = 0,
        output_tokens: int = 0, reasoning_tokens: int = 0,
    ) -> UsageEvent:
        event = UsageEvent(
            id=event_id,
            tenant_id=tenant_id,
            usage_type=usage_type,
            quantity=quantity,
            idempotency_key=idempotency_key,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )
        db.add(event)
        db.flush()
        return event

    @staticmethod
    def get_by_tenant_and_key(db: Session, tenant_id: str, idempotency_key: str) -> UsageEvent | None:
        return db.query(UsageEvent).filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == idempotency_key
        ).first()

    @staticmethod
    def get_current_month_usage(db: Session, tenant_id: str, usage_type: str) -> int:
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

        result = db.query(func.sum(UsageEvent.quantity)).filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.usage_type == usage_type,
            UsageEvent.created_at >= start_of_month
        ).scalar()

        return result if result is not None else 0

    @staticmethod
    def get_current_month_token_breakdown(db: Session, tenant_id: str) -> dict:
        """Return aggregated token sub-categories for the current month."""
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

        row = db.query(
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cached_input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.reasoning_tokens), 0),
        ).filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.usage_type == "ai_tokens",
            UsageEvent.created_at >= start_of_month,
        ).one()

        return {
            "input_tokens": row[0],
            "cached_input_tokens": row[1],
            "output_tokens": row[2],
            "reasoning_tokens": row[3],
        }
