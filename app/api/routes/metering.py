from fastapi import APIRouter, Depends, Header, status, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.generate import GenerateRequest, GenerateResponse
from app.schemas.usage_response import TenantUsageResponse
from app.services import MeterService

router = APIRouter()


@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_201_CREATED)
def generate_usage(
    payload: GenerateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    # Ensure header idempotency_key matches request body idempotency_key if both present
    if payload.idempotency_key != idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header does not match body idempotency_key."
        )

    event, status_flag = MeterService.record(
        db=db,
        tenant_id=payload.tenant_id,
        usage_type=payload.usage_type,
        quantity=payload.quantity,
        idempotency_key=idempotency_key,
        input_tokens=payload.input_tokens,
        cached_input_tokens=payload.cached_input_tokens,
        output_tokens=payload.output_tokens,
        reasoning_tokens=payload.reasoning_tokens,
    )

    return GenerateResponse(
        event_id=event.id,
        tenant_id=event.tenant_id,
        usage_type=event.usage_type,
        quantity=event.quantity,
        idempotency_key=event.idempotency_key,
        created_at=str(event.created_at),
        status=status_flag
    )


@router.get("/usage", response_model=TenantUsageResponse, status_code=status.HTTP_200_OK)
def get_usage(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    return MeterService.get_tenant_usage(db=db, tenant_id=tenant_id)
