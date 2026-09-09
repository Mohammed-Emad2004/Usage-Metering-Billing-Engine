from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.repositories import TenantRepository, SubscriptionRepository, UsageRepository
from app.schemas.usage import UsageType
from app.schemas.usage_response import TenantUsageResponse, UsageMetricDetail
from app.services.cost import calculate_api_call_cost, calculate_ai_token_cost, calculate_total_cost
import uuid


class QuotaService:
    @staticmethod
    def check_quota(db: Session, tenant_id: str, usage_type: UsageType, requested_quantity: int) -> tuple[int, int]:
        tenant = TenantRepository.get_by_id(db, tenant_id)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant with ID '{tenant_id}' not found."
            )

        subscription = SubscriptionRepository.get_by_tenant_id(db, tenant_id)
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Tenant '{tenant_id}' has no active subscription/plan."
            )

        if subscription.status in ["past_due", "canceled"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Subscription is '{subscription.status}'. Payment or upgrade required."
            )

        plan = subscription.plan
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Subscription plan details missing."
            )

        current_usage = UsageRepository.get_current_month_usage(db, tenant_id, usage_type.value)

        limit = plan.api_call_limit if usage_type == UsageType.API_CALLS else plan.ai_token_limit

        if current_usage + requested_quantity > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Usage quota exceeded",
                    "usage_type": usage_type.value,
                    "current_usage": current_usage,
                    "requested_quantity": requested_quantity,
                    "limit": limit,
                    "reason": f"Request would cross monthly limit of {limit} for {usage_type.value}."
                }
            )

        return current_usage, limit


class MeterService:
    @staticmethod
    def record(
        db: Session, tenant_id: str, usage_type: UsageType, quantity: int, idempotency_key: str,
        input_tokens: int = 0, cached_input_tokens: int = 0,
        output_tokens: int = 0, reasoning_tokens: int = 0,
    ):
        # Check idempotency FIRST — retry must not fail with 429 or create duplicates
        existing_event = UsageRepository.get_by_tenant_and_key(db, tenant_id, idempotency_key)
        if existing_event:
            return existing_event, "reused"

        # Validate tenant and check quota only for new requests
        QuotaService.check_quota(db, tenant_id, usage_type, quantity)

        event_id = f"evt_{uuid.uuid4().hex}"
        try:
            event = UsageRepository.create(
                db=db,
                event_id=event_id,
                tenant_id=tenant_id,
                usage_type=usage_type.value,
                quantity=quantity,
                idempotency_key=idempotency_key,
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
            )
            db.commit()
            return event, "recorded"
        except IntegrityError:
            db.rollback()
            # Concurrent duplicate caught by UNIQUE(tenant_id, idempotency_key) constraint
            existing_event = UsageRepository.get_by_tenant_and_key(db, tenant_id, idempotency_key)
            if existing_event:
                return existing_event, "reused"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency conflict detected."
            )

    @staticmethod
    def get_tenant_usage(db: Session, tenant_id: str) -> TenantUsageResponse:
        tenant = TenantRepository.get_by_id(db, tenant_id)
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant with ID '{tenant_id}' not found."
            )

        subscription = SubscriptionRepository.get_by_tenant_id(db, tenant_id)
        if not subscription or not subscription.plan:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Tenant '{tenant_id}' has no valid subscription/plan."
            )

        plan = subscription.plan
        api_used = UsageRepository.get_current_month_usage(db, tenant_id, UsageType.API_CALLS.value)
        ai_used = UsageRepository.get_current_month_usage(db, tenant_id, UsageType.AI_TOKENS.value)

        # Cost calculation
        api_cost = calculate_api_call_cost(api_used)

        token_breakdown = UsageRepository.get_current_month_token_breakdown(db, tenant_id)
        ai_cost = calculate_ai_token_cost(
            input_tokens=token_breakdown["input_tokens"],
            cached_input_tokens=token_breakdown["cached_input_tokens"],
            output_tokens=token_breakdown["output_tokens"],
            reasoning_tokens=token_breakdown["reasoning_tokens"],
        )

        total = calculate_total_cost(api_cost, ai_cost)

        return TenantUsageResponse(
            tenant_id=tenant.id,
            plan_id=plan.id,
            subscription_status=subscription.status,
            api_calls=UsageMetricDetail(used=api_used, limit=plan.api_call_limit, cost=api_cost),
            ai_tokens=UsageMetricDetail(used=ai_used, limit=plan.ai_token_limit, cost=ai_cost),
            total_cost=total,
        )
