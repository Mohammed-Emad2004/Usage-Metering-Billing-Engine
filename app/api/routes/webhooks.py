from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services.stripe import StripeService

router = APIRouter()


@router.post("/webhooks/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="Stripe-Signature"),
    db: Session = Depends(get_db)
):
    payload = await request.body()

    event = StripeService.verify_webhook_signature(payload=payload, sig_header=stripe_signature)

    is_new = StripeService.record_event(
        db=db,
        stripe_event_id=event.id,
        event_type=event.type,
        payload=payload.decode("utf-8"),
    )

    if not is_new:
        return {"status": "already_processed"}

    if event.type == "checkout.session.completed":
        StripeService.handle_checkout_completed(db=db, event=event)
    elif event.type == "customer.subscription.updated":
        StripeService.handle_subscription_updated(db=db, event=event)
    elif event.type == "customer.subscription.deleted":
        StripeService.handle_subscription_deleted(db=db, event=event)

    db.commit()
    return {"status": "processed"}
