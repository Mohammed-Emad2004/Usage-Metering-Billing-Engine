"""
Integration tests for cost calculation in GET /usage.

Tests that the usage endpoint correctly exposes cost fields
calculated from stored token breakdowns.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from tests.conftest import TestSessionLocal


class TestUsageCostFields:
    def test_usage_response_includes_cost_fields(self, client):
        response = client.get("/usage?tenant_id=tenant_free_1")
        assert response.status_code == 200
        data = response.json()
        assert "cost" in data["api_calls"]
        assert "cost" in data["ai_tokens"]
        assert "total_cost" in data

    def test_zero_usage_zero_cost(self, client):
        response = client.get("/usage?tenant_id=tenant_free_1")
        data = response.json()
        assert data["api_calls"]["used"] == 0
        assert data["api_calls"]["cost"] == 0
        assert data["ai_tokens"]["used"] == 0
        assert data["ai_tokens"]["cost"] == 0
        assert data["total_cost"] == 0

    def test_api_call_cost_calculation(self, client):
        # Record 5 API calls (each costs 1 cent)
        for i in range(5):
            client.post(
                "/generate",
                json={
                    "tenant_id": "tenant_free_1",
                    "usage_type": "api_calls",
                    "quantity": 1,
                    "idempotency_key": f"cost_api_{i}"
                },
                headers={"Idempotency-Key": f"cost_api_{i}"}
            )

        response = client.get("/usage?tenant_id=tenant_free_1")
        data = response.json()
        assert data["api_calls"]["used"] == 5
        assert data["api_calls"]["cost"] == 5  # 5 calls * 1 cent = 5 cents
        assert data["total_cost"] == 5

    def test_ai_tokens_without_breakdown_defaults_to_input(self, client):
        # Send ai_tokens without sub-category breakdown (backward compatible)
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 3000,
                "idempotency_key": "cost_ai_nobreak"
            },
            headers={"Idempotency-Key": "cost_ai_nobreak"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        assert data["ai_tokens"]["used"] == 3000
        # 3000 input tokens at 3 cents/1k = 9 cents
        assert data["ai_tokens"]["cost"] == 9

    def test_ai_tokens_with_input_breakdown(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 2000,
                "idempotency_key": "cost_ai_input",
                "input_tokens": 2000,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "cost_ai_input"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        # 2000 input tokens at 3 cents/1k = 6 cents
        assert data["ai_tokens"]["cost"] == 6

    def test_ai_tokens_with_cached_breakdown(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 2000,
                "idempotency_key": "cost_ai_cached",
                "input_tokens": 0,
                "cached_input_tokens": 2000,
                "output_tokens": 0,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "cost_ai_cached"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        # 2000 cached input tokens at 1 cent/1k = 2 cents
        assert data["ai_tokens"]["cost"] == 2

    def test_ai_tokens_with_output_breakdown(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 2000,
                "idempotency_key": "cost_ai_output",
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 2000,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "cost_ai_output"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        # 2000 output tokens at 15 cents/1k = 30 cents
        assert data["ai_tokens"]["cost"] == 30

    def test_ai_tokens_with_reasoning_breakdown(self, client):
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 2000,
                "idempotency_key": "cost_ai_reason",
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 2000,
            },
            headers={"Idempotency-Key": "cost_ai_reason"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        # 2000 reasoning tokens at 15 cents/1k = 30 cents (same as output)
        assert data["ai_tokens"]["cost"] == 30

    def test_mixed_token_types_cost(self, client):
        # 1000 input (3) + 1000 cached (1) + 1000 output (15) + 500 reasoning (7) = 26
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 3500,
                "idempotency_key": "cost_ai_mixed",
                "input_tokens": 1000,
                "cached_input_tokens": 1000,
                "output_tokens": 1000,
                "reasoning_tokens": 500,
            },
            headers={"Idempotency-Key": "cost_ai_mixed"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        # input: 1000*3//1000 = 3
        # cached: 1000*1//1000 = 1
        # output: 1000*15//1000 = 15
        # reasoning: 500*15//1000 = 7
        assert data["ai_tokens"]["cost"] == 3 + 1 + 15 + 7

    def test_total_cost_sums_api_and_ai(self, client):
        # API calls
        for i in range(3):
            client.post(
                "/generate",
                json={
                    "tenant_id": "tenant_pro_1",
                    "usage_type": "api_calls",
                    "quantity": 1,
                    "idempotency_key": f"cost_total_api_{i}"
                },
                headers={"Idempotency-Key": f"cost_total_api_{i}"}
            )

        # AI tokens with output
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 1000,
                "idempotency_key": "cost_total_ai",
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 1000,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "cost_total_ai"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        assert data["api_calls"]["cost"] == 3  # 3 calls * 1 cent
        assert data["ai_tokens"]["cost"] == 15  # 1000 output * 15/1k
        assert data["total_cost"] == 18  # 3 + 15

    def test_cost_accumulates_across_events(self, client):
        # Two events for the same tenant
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 1000,
                "idempotency_key": "cost_accum_1",
                "input_tokens": 1000,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "cost_accum_1"}
        )
        client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 1000,
                "idempotency_key": "cost_accum_2",
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 1000,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "cost_accum_2"}
        )

        response = client.get("/usage?tenant_id=tenant_pro_1")
        data = response.json()
        # input: 1000*3//1000 = 3
        # output: 1000*15//1000 = 15
        assert data["ai_tokens"]["cost"] == 18
        assert data["ai_tokens"]["used"] == 2000

    def test_response_still_has_required_fields(self, client):
        response = client.get("/usage?tenant_id=tenant_free_1")
        data = response.json()
        # All original fields still present
        assert data["tenant_id"] == "tenant_free_1"
        assert data["plan_id"] == "free"
        assert data["subscription_status"] == "active"
        assert "used" in data["api_calls"]
        assert "limit" in data["api_calls"]
        assert "used" in data["ai_tokens"]
        assert "limit" in data["ai_tokens"]


class TestTokenBreakdownValidation:
    def test_breakdown_not_matching_quantity_rejected(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 1000,
                "idempotency_key": "val_bad_break",
                "input_tokens": 500,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "val_bad_break"}
        )
        assert response.status_code == 422

    def test_breakdown_matching_quantity_accepted(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 1000,
                "idempotency_key": "val_good_break",
                "input_tokens": 500,
                "cached_input_tokens": 200,
                "output_tokens": 300,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "val_good_break"}
        )
        assert response.status_code == 201

    def test_no_breakdown_defaults_to_input(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 1000,
                "idempotency_key": "val_no_break",
            },
            headers={"Idempotency-Key": "val_no_break"}
        )
        assert response.status_code == 201

    def test_api_calls_ignore_token_breakdown(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_free_1",
                "usage_type": "api_calls",
                "quantity": 5,
                "idempotency_key": "val_api_break",
                "input_tokens": 999,
                "cached_input_tokens": 999,
                "output_tokens": 999,
                "reasoning_tokens": 999,
            },
            headers={"Idempotency-Key": "val_api_break"}
        )
        assert response.status_code == 201

    def test_negative_breakdown_rejected(self, client):
        response = client.post(
            "/generate",
            json={
                "tenant_id": "tenant_pro_1",
                "usage_type": "ai_tokens",
                "quantity": 1000,
                "idempotency_key": "val_neg_break",
                "input_tokens": -100,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
            },
            headers={"Idempotency-Key": "val_neg_break"}
        )
        assert response.status_code == 422


class TestCostIdempotency:
    def test_idempotent_reuse_does_not_double_cost(self, client):
        payload = {
            "tenant_id": "tenant_pro_1",
            "usage_type": "ai_tokens",
            "quantity": 3000,
            "idempotency_key": "cost_idem_1",
            "input_tokens": 3000,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        }
        res1 = client.post("/generate", json=payload, headers={"Idempotency-Key": "cost_idem_1"})
        assert res1.status_code == 201
        assert res1.json()["status"] == "recorded"

        res2 = client.post("/generate", json=payload, headers={"Idempotency-Key": "cost_idem_1"})
        assert res2.status_code == 201
        assert res2.json()["status"] == "reused"

        usage = client.get("/usage?tenant_id=tenant_pro_1").json()
        assert usage["ai_tokens"]["used"] == 3000
        assert usage["ai_tokens"]["cost"] == 9  # 3000 * 3 // 1000
