from pydantic import BaseModel, Field, model_validator
from app.schemas.usage import UsageType


class GenerateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, description="The unique ID of the tenant")
    usage_type: UsageType = Field(..., description="Type of usage: api_calls or ai_tokens")
    quantity: int = Field(..., gt=0, description="Quantity of usage (must be positive integer)")
    idempotency_key: str = Field(..., min_length=1, description="Unique key for request idempotency")

    # Token sub-category breakdown (required for ai_tokens, ignored for api_calls)
    input_tokens: int = Field(default=0, ge=0, description="Number of input tokens")
    cached_input_tokens: int = Field(default=0, ge=0, description="Number of cached input tokens")
    output_tokens: int = Field(default=0, ge=0, description="Number of output tokens")
    reasoning_tokens: int = Field(default=0, ge=0, description="Number of reasoning tokens (billed as output)")

    @model_validator(mode="after")
    def validate_token_breakdown(self) -> "GenerateRequest":
        if self.usage_type == UsageType.AI_TOKENS:
            breakdown_sum = (
                self.input_tokens + self.cached_input_tokens
                + self.output_tokens + self.reasoning_tokens
            )
            if breakdown_sum > 0 and breakdown_sum != self.quantity:
                raise ValueError(
                    f"Token breakdown must sum to quantity. "
                    f"Got {breakdown_sum} breakdown tokens but quantity is {self.quantity}."
                )
            # Backward compatibility: if no breakdown provided, treat all as input tokens
            if breakdown_sum == 0:
                self.input_tokens = self.quantity
        return self


class GenerateResponse(BaseModel):
    event_id: str
    tenant_id: str
    usage_type: str
    quantity: int
    idempotency_key: str
    created_at: str
    status: str = "recorded"
