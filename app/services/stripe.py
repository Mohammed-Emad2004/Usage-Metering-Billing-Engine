import json
import uuid
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import stripe

from app.config import settings
from app.db.models.tenant import Tenant
from app.db.models.plan import Plan
from app.db.models.subscription import Subscription
from app.db.models.stripe_event import StripeEvent
from app.repositories import TenantRepository, SubscriptionRepository


class StripeService:
    @staticmethod
    def _get_stripe_client() -> stripe.StripeClient:
        if not settings.STRIPE_SECRET_KEY or settings.STRIPE_SECRET_KEY == "sk_test_placeholder":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe is not configured. Set STRIPE_SECRET_KEY in .env."
            )
        return stripe.StripeClient(api_key=settings.STRIPE_SECRET_KEY)

    @staticmethod
    def create_checkout_session(db: Session, tenant_id: str) -> dict:
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
                detail=f"Tenant '{tenant_id}' has no subscription."
            )

        if subscription.plan_id == "pro" and subscription.status == "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tenant '{tenant_id}' is already on the Pro plan."
            )

        client = StripeService._get_stripe_client()

        if subscription.stripe_customer_id:
            stripe_customer_id = subscription.stripe_customer_id
        else:
            customer = client.customers.create(
                name=tenant.name,
                metadata={"tenant_id": tenant_id}
            )
            stripe_customer_id = customer.id
            subscription.stripe_customer_id = stripe_customer_id
            db.commit()

        if not settings.STRIPE_PRO_PRICE_ID or settings.STRIPE_PRO_PRICE_ID == "price_test_placeholder":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe Pro price is not configured. Set STRIPE_PRO_PRICE_ID in .env."
            )

        session = client.checkout.sessions.create(
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{
                "price": settings.STRIPE_PRO_PRICE_ID,
                "quantity": 1,
            }],
            success_url="http://localhost:8000/billing/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://localhost:8000/billing/cancel",
            metadata={"tenant_id": tenant_id},
        )

        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "tenant_id": tenant_id,
        }

    @staticmethod
    def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
        if not settings.STRIPE_WEBHOOK_SECRET or settings.STRIPE_WEBHOOK_SECRET == "whsec_placeholder":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe webhook secret is not configured."
            )
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
            return event
        except (stripe.error.SignatureVerificationError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook signature."
            )

    @staticmethod
    def record_event(db: Session, stripe_event_id: str, event_type: str, payload: str) -> bool:
        """Record a Stripe event using a savepoint. Returns True if newly recorded, False if duplicate."""
        savepoint = db.begin_nested()
        try:
            event_record = StripeEvent(
                id=f"sevt_{uuid.uuid4().hex}",
                stripe_event_id=stripe_event_id,
                event_type=event_type,
                payload=payload,
            )
            db.add(event_record)
            db.flush()
            return True
        except IntegrityError:
            savepoint.rollback()
            return False

    @staticmethod
    def handle_checkout_completed(db: Session, event: stripe.Event) -> None:
        session_data = event.data.object
        tenant_id = session_data.get("metadata", {}).get("tenant_id")
        if not tenant_id:
            return

        stripe_customer_id = session_data.get("customer")
        stripe_subscription_id = session_data.get("subscription")

        subscription = SubscriptionRepository.get_by_tenant_id(db, tenant_id)
        if not subscription:
            return

        subscription.stripe_customer_id = stripe_customer_id
        subscription.stripe_subscription_id = stripe_subscription_id
        subscription.plan_id = "pro"
        subscription.status = "active"

        pro_plan = db.query(Plan).filter(Plan.id == "pro").first()
        if pro_plan:
            subscription.plan_id = pro_plan.id

        if session_data.get("subscription_details", {}).get("trial_end"):
            from datetime import datetime, timezone
            subscription.current_period_end = datetime.fromtimestamp(
                session_data["subscription_details"]["trial_end"], tz=timezone.utc
            )

        db.flush()

    @staticmethod
    def handle_subscription_updated(db: Session, event: stripe.Event) -> None:
        sub_data = event.data.object
        stripe_subscription_id = sub_data.get("id")
        stripe_customer_id = sub_data.get("customer")
        stripe_status = sub_data.get("status")

        subscription = None
        if stripe_subscription_id:
            subscription = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == stripe_subscription_id
            ).first()

        if not subscription and stripe_customer_id:
            subscription = db.query(Subscription).filter(
                Subscription.stripe_customer_id == stripe_customer_id
            ).first()

        if not subscription:
            return

        status_map = {
            "active": "active",
            "trialing": "active",
            "past_due": "past_due",
            "unpaid": "past_due",
            "canceled": "canceled",
            "incomplete_expired": "canceled",
            "incomplete": "active",
        }
        subscription.status = status_map.get(stripe_status, "active")

        if sub_data.get("items", {}).get("data"):
            price_id = sub_data["items"]["data"][0].get("price", {}).get("id")
            if price_id == settings.STRIPE_PRO_PRICE_ID:
                subscription.plan_id = "pro"

        from datetime import datetime, timezone
        if sub_data.get("current_period_start"):
            subscription.current_period_start = datetime.fromtimestamp(
                sub_data["current_period_start"], tz=timezone.utc
            )
        if sub_data.get("current_period_end"):
            subscription.current_period_end = datetime.fromtimestamp(
                sub_data["current_period_end"], tz=timezone.utc
            )

        db.flush()

    @staticmethod
    def handle_subscription_deleted(db: Session, event: stripe.Event) -> None:
        sub_data = event.data.object
        stripe_subscription_id = sub_data.get("id")

        subscription = None
        if stripe_subscription_id:
            subscription = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == stripe_subscription_id
            ).first()

        if not subscription:
            stripe_customer_id = sub_data.get("customer")
            if stripe_customer_id:
                subscription = db.query(Subscription).filter(
                    Subscription.stripe_customer_id == stripe_customer_id
                ).first()

        if not subscription:
            return

        subscription.status = "canceled"
        db.flush()
