import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base, get_db
from app.main import app
from app.db.models import Tenant, Plan, Subscription, UsageEvent, StripeEvent

TEST_DATABASE_URL = "postgresql://postgres@localhost:5432/flyrank_metering"

test_engine = create_engine(
    TEST_DATABASE_URL,
    poolclass=StaticPool,
    connect_args={"options": "-csearch_path=public"},
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestSessionLocal()
    try:
        free_plan = Plan(id="free", name="Free Test Plan", api_call_limit=10, ai_token_limit=100)
        pro_plan = Plan(id="pro", name="Pro Test Plan", api_call_limit=1000, ai_token_limit=10000)
        db.add(free_plan)
        db.add(pro_plan)

        tenant_free = Tenant(id="tenant_free_1", name="Test Tenant Free")
        sub_free = Subscription(
            id="sub_1", tenant_id="tenant_free_1", plan_id="free", status="active",
            stripe_customer_id="cus_free_1", stripe_subscription_id="sub_free_stripe_1"
        )
        db.add(tenant_free)
        db.add(sub_free)

        tenant_pro = Tenant(id="tenant_pro_1", name="Test Tenant Pro")
        sub_pro = Subscription(
            id="sub_2", tenant_id="tenant_pro_1", plan_id="pro", status="active",
            stripe_customer_id="cus_pro_1", stripe_subscription_id="sub_pro_stripe_1"
        )
        db.add(tenant_pro)
        db.add(sub_pro)

        tenant_inactive = Tenant(id="tenant_inactive_1", name="Test Tenant Inactive")
        sub_inactive = Subscription(
            id="sub_3", tenant_id="tenant_inactive_1", plan_id="free", status="past_due",
            stripe_customer_id="cus_inactive_1", stripe_subscription_id="sub_inactive_stripe_1"
        )
        db.add(tenant_inactive)
        db.add(sub_inactive)

        db.commit()
    finally:
        db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def db_session():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


def make_stripe_event(event_id, event_type, data_object):
    mock_event = MagicMock()
    mock_event.id = event_id
    mock_event.type = event_type
    mock_event.data.object = data_object
    return mock_event


def make_checkout_session(tenant_id, customer_id, subscription_id):
    return {
        "customer": customer_id,
        "subscription": subscription_id,
        "metadata": {"tenant_id": tenant_id},
        "subscription_details": {},
    }


def make_stripe_subscription(subscription_id, customer_id, stripe_status, price_id, period_start=None, period_end=None):
    sub = {
        "id": subscription_id,
        "customer": customer_id,
        "status": stripe_status,
        "items": {
            "data": [{"price": {"id": price_id}}]
        },
    }
    if period_start:
        sub["current_period_start"] = period_start
    if period_end:
        sub["current_period_end"] = period_end
    return sub
