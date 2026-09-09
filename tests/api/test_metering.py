import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.database import Base, get_db
from app.db.models import Tenant, Plan, Subscription, UsageEvent
from tests.conftest import test_engine, TestSessionLocal


class TestFirstUsageRequestSucceeds:
    def test_first_request_returns_201(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 2,
                "idempotency_key": "key_001"
            },
            headers={"Idempotency-Key": "key_001"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "recorded"
        assert data["quantity"] == 2
        assert data["tenant_id"] == "tenant_free_1"
        assert data["usage_type"] == "api_calls"
        assert data["event_id"] is not None


class TestIdempotentDuplicateRequest:
    def test_same_tenant_same_key_returns_reused(self, client):
        payload = {
            "tenant_id": "tenant_free_1",
            "usage_type": "api_calls",
            "quantity": 3,
            "idempotency_key": "key_dup_1"
        }
        res1 = client.post("/generate", json=payload, headers={"Idempotency-Key": "key_dup_1"})
        assert res1.status_code == 201
        assert res1.json()["status"] == "recorded"

        res2 = client.post("/generate", json=payload, headers={"Idempotency-Key": "key_dup_1"})
        assert res2.status_code == 201
        assert res2.json()["status"] == "reused"
        assert res2.json()["event_id"] == res1.json()["event_id"]

        usage_res = client.get("/usage?tenant_id=tenant_free_1")
        assert usage_res.status_code == 200
        assert usage_res.json()["api_calls"]["used"] == 3

    def test_duplicate_does_not_create_second_event_in_db(self, client):
        payload = {
            "tenant_id": "tenant_free_1",
            "usage_type": "api_calls",
            "quantity": 5,
            "idempotency_key": "key_db_check"
        }
        client.post("/generate", json=payload, headers={"Idempotency-Key": "key_db_check"})
        client.post("/generate", json=payload, headers={"Idempotency-Key": "key_db_check"})

        db = TestSessionLocal()
        try:
            count = db.query(UsageEvent).filter(
                UsageEvent.tenant_id == "tenant_free_1",
                UsageEvent.idempotency_key == "key_db_check"
            ).count()
            assert count == 1
            event = db.query(UsageEvent).filter(
                UsageEvent.tenant_id == "tenant_free_1",
                UsageEvent.idempotency_key == "key_db_check"
            ).first()
            assert event.quantity == 5
        finally:
            db.close()


class TestSameKeyDifferentTenants:
    def test_different_tenants_same_key_both_succeed(self, client):
        payload_t1 = {
            "tenant_id": "tenant_free_1",
            "usage_type": "api_calls",
            "quantity": 1,
            "idempotency_key": "shared_key_123"
        }
        payload_t2 = {
            "tenant_id": "tenant_pro_1",
            "usage_type": "api_calls",
            "quantity": 5,
            "idempotency_key": "shared_key_123"
        }

        res1 = client.post("/generate", json=payload_t1, headers={"Idempotency-Key": "shared_key_123"})
        assert res1.status_code == 201

        res2 = client.post("/generate", json=payload_t2, headers={"Idempotency-Key": "shared_key_123"})
        assert res2.status_code == 201
        assert res1.json()["event_id"] != res2.json()["event_id"]


class TestInvalidQuantity:
    def test_zero_quantity_rejected(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 0,
                "idempotency_key": "key_zero"
            },
            headers={"Idempotency-Key": "key_zero"}
        )
        assert response.status_code == 422

    def test_negative_quantity_rejected(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": -1,
                "idempotency_key": "key_neg"
            },
            headers={"Idempotency-Key": "key_neg"}
        )
        assert response.status_code == 422


class TestInvalidTenant:
    def test_nonexistent_tenant_returns_404(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "non_existent_tenant",
                "usage_type": "api_calls",
                "quantity": 1,
                "idempotency_key": "key_notfound"
            },
            headers={"Idempotency-Key": "key_notfound"}
        )
        assert response.status_code == 404

    def test_missing_idempotency_key_returns_422(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 1,
                "idempotency_key": "key_valid"
            }
        )
        assert response.status_code == 422

    def test_usage_endpoint_nonexistent_tenant_returns_404(self, client):
        response = client.get("/usage?tenant_id=non_existent_tenant")
        assert response.status_code == 404


class TestUsageBelowQuota:
    def test_usage_within_quota_succeeds(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 5,
                "idempotency_key": "key_below"
            },
            headers={"Idempotency-Key": "key_below"}
        )
        assert response.status_code == 201

        usage_res = client.get("/usage?tenant_id=tenant_free_1")
        assert usage_res.status_code == 200
        assert usage_res.json()["api_calls"]["used"] == 5


class TestUsageExactlyAtQuota:
    def test_usage_exactly_at_limit_succeeds(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 10,
                "idempotency_key": "key_exact"
            },
            headers={"Idempotency-Key": "key_exact"}
        )
        assert response.status_code == 201
        assert response.json()["status"] == "recorded"

        usage_res = client.get("/usage?tenant_id=tenant_free_1")
        assert usage_res.json()["api_calls"]["used"] == 10
        assert usage_res.json()["api_calls"]["limit"] == 10


class TestUsageExceedingQuota:
    def test_over_quota_returns_429(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 10,
                "idempotency_key": "key_fill"
            },
            headers={"Idempotency-Key": "key_fill"}
        )

        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 1,
                "idempotency_key": "key_exceed"
            },
            headers={"Idempotency-Key": "key_exceed"}
        )
        assert response.status_code == 429
        detail = response.json()["detail"]
        assert detail["usage_type"] == "api_calls"
        assert detail["current_usage"] == 10
        assert detail["requested_quantity"] == 1
        assert detail["limit"] == 10

    def test_rejected_request_does_not_create_usage_event(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 10,
                "idempotency_key": "key_fill2"
            },
            headers={"Idempotency-Key": "key_fill2"}
        )

        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 1,
                "idempotency_key": "key_exceed2"
            },
            headers={"Idempotency-Key": "key_exceed2"}
        )

        db = TestSessionLocal()
        try:
            count = db.query(UsageEvent).filter(
                UsageEvent.tenant_id == "tenant_free_1",
                UsageEvent.idempotency_key == "key_exceed2"
            ).count()
            assert count == 0
        finally:
            db.close()

    def test_different_usage_type_within_quota_succeeds(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "ai_tokens",
                "quantity": 100,
                "idempotency_key": "key_ai"
            },
            headers={"Idempotency-Key": "key_ai"}
        )
        assert response.status_code == 201

    def test_ai_tokens_over_quota_returns_429(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "ai_tokens",
                "quantity": 100,
                "idempotency_key": "key_ai_fill"
            },
            headers={"Idempotency-Key": "key_ai_fill"}
        )

        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "ai_tokens",
                "quantity": 1,
                "idempotency_key": "key_ai_exceed"
            },
            headers={"Idempotency-Key": "key_ai_exceed"}
        )
        assert response.status_code == 429


class TestMonthlyAggregation:
    def test_current_month_events_count(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "api_calls",
                "quantity": 100,
                "idempotency_key": "key_month_1"
            },
            headers={"Idempotency-Key": "key_month_1"}
        )
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "api_calls",
                "quantity": 200,
                "idempotency_key": "key_month_2"
            },
            headers={"Idempotency-Key": "key_month_2"}
        )

        usage_res = client.get("/usage?tenant_id=tenant_pro_1")
        assert usage_res.status_code == 200
        assert usage_res.json()["api_calls"]["used"] == 300

    def test_old_month_events_not_counted(self, client):
        db = TestSessionLocal()
        try:
            from datetime import datetime, timezone, timedelta
            last_month = datetime.now(timezone.utc) - timedelta(days=35)
            old_event = UsageEvent(
                id="evt_old",
                tenant_id="tenant_pro_1",
                usage_type="api_calls",
                quantity=9999,
                idempotency_key="old_month_key",
                created_at=last_month
            )
            db.add(old_event)
            db.commit()
        finally:
            db.close()

        usage_res = client.get("/usage?tenant_id=tenant_pro_1")
        assert usage_res.status_code == 200
        assert usage_res.json()["api_calls"]["used"] == 0


class TestInactiveSubscriptionRejected:
    def test_past_due_subscription_returns_402(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_inactive_1",
                "usage_type": "api_calls",
                "quantity": 1,
                "idempotency_key": "key_inactive"
            },
            headers={"Idempotency-Key": "key_inactive"}
        )
        assert response.status_code == 402


class TestNoSubscriptionReturns402:
    def test_tenant_without_subscription_returns_402(self, client):
        db = TestSessionLocal()
        try:
            tenant_no_sub = Tenant(id="tenant_nosub", name="No Subscription Tenant")
            db.add(tenant_no_sub)
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_nosub",
                "usage_type": "api_calls",
                "quantity": 1,
                "idempotency_key": "key_nosub"
            },
            headers={"Idempotency-Key": "key_nosub"}
        )
        assert response.status_code == 402


class TestUsageReadAPI:
    def test_usage_returns_all_fields(self, client):
        response = client.get("/usage?tenant_id=tenant_free_1")
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "tenant_free_1"
        assert data["plan_id"] == "free"
        assert data["subscription_status"] == "active"
        assert "api_calls" in data
        assert "ai_tokens" in data
        assert "used" in data["api_calls"]
        assert "limit" in data["api_calls"]
        assert data["api_calls"]["limit"] == 10
        assert data["ai_tokens"]["limit"] == 100

    def test_pro_plan_usage_limits(self, client):
        response = client.get("/usage?tenant_id=tenant_pro_1")
        assert response.status_code == 200
        data = response.json()
        assert data["plan_id"] == "pro"
        assert data["api_calls"]["limit"] == 1000
        assert data["ai_tokens"]["limit"] == 10000


class TestConcurrencyIdempotency:
    def test_database_constraint_prevents_duplicate(self, client):
        payload = {
            "tenant_id": "tenant_pro_1",
            "usage_type": "api_calls",
            "quantity": 10,
            "idempotency_key": "key_concurrent"
        }

        results = []
        for _ in range(5):
            res = client.post("/generate", json=payload, headers={"Idempotency-Key": "key_concurrent"})
            results.append(res)

        recorded_count = sum(1 for r in results if r.json()["status"] == "recorded")
        reused_count = sum(1 for r in results if r.json()["status"] == "reused")
        assert recorded_count == 1
        assert reused_count == 4

        for r in results:
            assert r.json()["event_id"] == results[0].json()["event_id"]

        db = TestSessionLocal()
        try:
            db_count = db.query(UsageEvent).filter(
                UsageEvent.tenant_id == "tenant_pro_1",
                UsageEvent.idempotency_key == "key_concurrent"
            ).count()
            assert db_count == 1
        finally:
            db.close()
