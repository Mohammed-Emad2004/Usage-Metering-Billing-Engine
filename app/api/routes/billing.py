from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.billing import CheckoutRequest, CheckoutResponse
from app.services.stripe import StripeService

router = APIRouter()


@router.post("/billing/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
def create_checkout_session(
    payload: CheckoutRequest,
    db: Session = Depends(get_db)
):
    result = StripeService.create_checkout_session(db=db, tenant_id=payload.tenant_id)
    return CheckoutResponse(**result)
