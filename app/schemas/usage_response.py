from pydantic import BaseModel


class UsageMetricDetail(BaseModel):
    used: int
    limit: int
    cost: int = 0


class TenantUsageResponse(BaseModel):
    tenant_id: str
    plan_id: str
    subscription_status: str
    api_calls: UsageMetricDetail
    ai_tokens: UsageMetricDetail
    total_cost: int = 0
