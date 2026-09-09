from fastapi import APIRouter
from app.api.routes import health, metering, billing, webhooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(metering.router, tags=["metering"])
api_router.include_router(billing.router, tags=["billing"])
api_router.include_router(webhooks.router, tags=["webhooks"])
