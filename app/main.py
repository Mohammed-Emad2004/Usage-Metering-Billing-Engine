from fastapi import FastAPI
from app.api.routes import api_router
from app.config import settings

app = FastAPI(
    title="FlyRank Usage Metering & Billing Engine",
    version="0.1.0",
    description="Backend tracking capstone for usage metering and billing with FastAPI and SQLAlchemy."
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"message": "Welcome to FlyRank Usage Metering & Billing Engine API. Visit /docs for API documentation."}
