from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, description="The tenant upgrading to Pro")


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    tenant_id: str
