import hashlib
import hmac
import time
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.services.stripe import StripeService
from app.db.database import get_db
from app.db.models import Subscription, StripeEvent, Tenant, UsageEvent
from tests.conftest import (
    TestSessionLocal, make_stripe_event, make_checkout_session,
    make_stripe_subscription
)

TEST_WEBHOOK_SECRET = "whsec_test_secret_for_hmac_signing"


def generate_stripe_signature(payload: bytes, secret: str, timestamp: int = None) -> str:
    if timestamp is None:
        timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    sig = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={sig}"


# ─── CHECKOUT ENDPOINT ──────────────────────────────────────────

class TestCheckoutEndpoint:
    @patch("app.services.stripe.settings")
    @patch("app.services.stripe.StripeService._get_stripe_client")
    def test_existing_tenant_creates_checkout(self, mock_get_client, mock_settings, client):
        mock_settings.STRIPE_PRO_PRICE_ID = "price_test_pro"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.customers.create.return_value = MagicMock(id="cus_test_123")
        mock_client.checkout.sessions.create.return_value = MagicMock(
            id="cs_test_session", url="https://checkout.stripe.com/test_session"
        )
        response = client.post("/billing/checkout", json={"tenant_id": "tenant_free_1"})
        assert response.status_code == 201
        data = response.json()
        assert data["checkout_url"] == "https://checkout.stripe.com/test_session"
        assert data["session_id"] == "cs_test_session"
        assert data["tenant_id"] == "tenant_free_1"

    def test_missing_tenant_returns_404(self, client):
        response = client.post("/billing/checkout", json={"tenant_id": "nonexistent_tenant"})
        assert response.status_code == 404

    @patch("app.services.stripe.settings")
    @patch("app.services.stripe.StripeService._get_stripe_client")
    def test_configured_pro_price_is_used(self, mock_get_client, mock_settings, client):
        mock_settings.STRIPE_PRO_PRICE_ID = "price_test_pro"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.customers.create.return_value = MagicMock(id="cus_test_456")
        mock_client.checkout.sessions.create.return_value = MagicMock(
            id="cs_test_price", url="https://checkout.stripe.com/test_price"
        )
        client.post("/billing/checkout", json={"tenant_id": "tenant_free_1"})
        call_kwargs = mock_client.checkout.sessions.create.call_args
        line_items = call_kwargs.kwargs.get("line_items") or call_kwargs[1].get("line_items")
        assert line_items[0]["price"] == "price_test_pro"

    @patch("app.services.stripe.settings")
    @patch("app.services.stripe.StripeService._get_stripe_client")
    def test_stripe_customer_mapping_stored(self, mock_get_client, mock_settings, client):
        mock_settings.STRIPE_PRO_PRICE_ID = "price_test_pro"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.checkout.sessions.create.return_value = MagicMock(
            id="cs_test_mapping", url="https://checkout.stripe.com/test_mapping"
        )
        client.post("/billing/checkout", json={"tenant_id": "tenant_free_1"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(Subscription.tenant_id == "tenant_free_1").first()
            assert sub.stripe_customer_id == "cus_free_1"
        finally:
            db.close()

    def test_already_pro_tenant_returns_400(self, client):
        response = client.post("/billing/checkout", json={"tenant_id": "tenant_pro_1"})
        assert response.status_code == 400
        assert "already on the Pro plan" in response.json()["detail"]

    def test_no_subscription_tenant_returns_402(self, client):
        db = TestSessionLocal()
        try:
            tenant = Tenant(id="tenant_nosub_checkout", name="No Sub Checkout")
            db.add(tenant)
            db.commit()
        finally:
            db.close()
        response = client.post("/billing/checkout", json={"tenant_id": "tenant_nosub_checkout"})
        assert response.status_code == 402

    @patch("app.services.stripe.settings")
    @patch("app.services.stripe.StripeService._get_stripe_client")
    def test_reuses_existing_stripe_customer(self, mock_get_client, mock_settings, client):
        mock_settings.STRIPE_PRO_PRICE_ID = "price_test_pro"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.checkout.sessions.create.return_value = MagicMock(
            id="cs_reuse", url="https://checkout.stripe.com/reuse"
        )
        client.post("/billing/checkout", json={"tenant_id": "tenant_free_1"})
        mock_client.customers.create.assert_not_called()


# ─── WEBHOOK SIGNATURE (unit tests against verify_webhook_signature) ──

class TestWebhookSignature:
    def test_valid_signature_accepted(self):
        with patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
            payload = b'{"id":"evt_1","type":"checkout.session.completed","data":{"object":{}}}'
            sig = generate_stripe_signature(payload, TEST_WEBHOOK_SECRET)
            event = StripeService.verify_webhook_signature(payload, sig)
            assert event is not None
            assert event.id == "evt_1"

    def test_forged_signature_returns_400(self):
        with patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
            payload = b'{"id":"evt_forge","type":"checkout.session.completed","data":{"object":{}}}'
            wrong_sig = generate_stripe_signature(b'{"id":"evt_different"}', TEST_WEBHOOK_SECRET)
            with pytest.raises(HTTPException) as exc_info:
                StripeService.verify_webhook_signature(payload, wrong_sig)
            assert exc_info.value.status_code == 400

    def test_invalid_signature_no_db_mutation(self):
        with patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
            payload = b'{"id":"evt_nomut"}'
            wrong_sig = generate_stripe_signature(b'{"id":"evt_diff"}', TEST_WEBHOOK_SECRET)
            db = TestSessionLocal()
            try:
                count_before = db.query(StripeEvent).count()
            finally:
                db.close()
            with pytest.raises(HTTPException):
                StripeService.verify_webhook_signature(payload, wrong_sig)
            db = TestSessionLocal()
            try:
                count_after = db.query(StripeEvent).count()
                assert count_after == count_before
            finally:
                db.close()

    def test_missing_secret_returns_503(self):
        with patch("app.config.settings.STRIPE_WEBHOOK_SECRET", "whsec_placeholder"):
            with pytest.raises(HTTPException) as exc_info:
                StripeService.verify_webhook_signature(b'{}', "sig")
            assert exc_info.value.status_code == 503


# ─── checkout.session.completed ─────────────────────────────────

@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
class TestCheckoutSessionCompleted:
    @patch("stripe.Webhook.construct_event")
    def test_upgrades_free_to_pro(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_cs_1", "checkout.session.completed",
            make_checkout_session("tenant_free_1", "cus_cs_1", "sub_cs_1")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_cs_1"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(Subscription.tenant_id == "tenant_free_1").first()
            assert sub.plan_id == "pro"
            assert sub.status == "active"
            assert sub.stripe_customer_id == "cus_cs_1"
            assert sub.stripe_subscription_id == "sub_cs_1"
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_stripe_customer_id_stored(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_cs_2", "checkout.session.completed",
            make_checkout_session("tenant_free_1", "cus_new_id", "sub_new_id")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_cs_2"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(Subscription.tenant_id == "tenant_free_1").first()
            assert sub.stripe_customer_id == "cus_new_id"
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_stripe_subscription_id_stored(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_cs_3", "checkout.session.completed",
            make_checkout_session("tenant_free_1", "cus_cust", "sub_sub")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_cs_3"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(Subscription.tenant_id == "tenant_free_1").first()
            assert sub.stripe_subscription_id == "sub_sub"
        finally:
            db.close()


# ─── customer.subscription.updated ──────────────────────────────

@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
class TestSubscriptionUpdated:
    @patch("stripe.Webhook.construct_event")
    def test_active_subscription_synchronizes(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_sub_1", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "active", "price_test_pro",
                                     period_start=1700000000, period_end=1702592000)
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_sub_1"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_free_stripe_1"
            ).first()
            assert sub is not None
            assert sub.status == "active"
            assert sub.plan_id == "pro"
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_past_due_synchronizes(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_sub_2", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "past_due", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_sub_2"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_free_stripe_1"
            ).first()
            assert sub.status == "past_due"
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_plan_synchronizes_to_pro(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_sub_3", "customer.subscription.updated",
            make_stripe_subscription("sub_inactive_stripe_1", "cus_inactive_1", "active", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_sub_3"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_inactive_stripe_1"
            ).first()
            assert sub.plan_id == "pro"
            assert sub.status == "active"
        finally:
            db.close()


# ─── customer.subscription.deleted ──────────────────────────────

@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
class TestSubscriptionDeleted:
    @patch("stripe.Webhook.construct_event")
    def test_subscription_becomes_canceled(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_del_1", "customer.subscription.deleted",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "canceled", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_del_1"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_free_stripe_1"
            ).first()
            assert sub.status == "canceled"
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_tenant_remains_intact(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_del_2", "customer.subscription.deleted",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "canceled", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_del_2"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            tenant = db.query(Tenant).filter(Tenant.id == "tenant_free_1").first()
            assert tenant is not None
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_usage_history_remains_intact(self, mock_construct, client):
        db_setup = TestSessionLocal()
        try:
            db_setup.add(UsageEvent(
                id="evt_usage_del", tenant_id="tenant_free_1",
                usage_type="api_calls", quantity=5,
                idempotency_key="key_before_delete"
            ))
            db_setup.commit()
        finally:
            db_setup.close()

        mock_construct.return_value = make_stripe_event(
            "evt_del_3", "customer.subscription.deleted",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "canceled", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_del_3"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            usage = db.query(UsageEvent).filter(UsageEvent.id == "evt_usage_del").first()
            assert usage is not None
            assert usage.quantity == 5
        finally:
            db.close()


# ─── WEBHOOK IDEMPOTENCY ────────────────────────────────────────

@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
class TestWebhookIdempotency:
    @patch("stripe.Webhook.construct_event")
    def test_same_event_twice_processed_once(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_idem_1", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "active", "price_test_pro")
        )
        payload = json.dumps({"id": "evt_idem_1"})
        res1 = client.post("/webhooks/stripe", content=payload,
                           headers={"Stripe-Signature": "sig"})
        assert res1.json()["status"] == "processed"
        res2 = client.post("/webhooks/stripe", content=payload,
                           headers={"Stripe-Signature": "sig"})
        assert res2.json()["status"] == "already_processed"

    @patch("stripe.Webhook.construct_event")
    def test_database_contains_one_stripe_event_record(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_idem_2", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "active", "price_test_pro")
        )
        payload = json.dumps({"id": "evt_idem_2"})
        client.post("/webhooks/stripe", content=payload,
                    headers={"Stripe-Signature": "sig"})
        client.post("/webhooks/stripe", content=payload,
                    headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            count = db.query(StripeEvent).filter(
                StripeEvent.stripe_event_id == "evt_idem_2"
            ).count()
            assert count == 1
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_subscription_state_not_corrupted(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_idem_3", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "active", "price_test_pro")
        )
        payload = json.dumps({"id": "evt_idem_3"})
        client.post("/webhooks/stripe", content=payload,
                    headers={"Stripe-Signature": "sig"})
        client.post("/webhooks/stripe", content=payload,
                    headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_free_stripe_1"
            ).first()
            assert sub.status == "active"
        finally:
            db.close()


# ─── UNKNOWN EVENT TYPE ─────────────────────────────────────────

@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
class TestUnknownEventType:
    @patch("stripe.Webhook.construct_event")
    def test_unknown_event_ignored_safely(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_unknown", "invoice.payment_failed", {}
        )
        response = client.post("/webhooks/stripe", content=json.dumps({"id": "evt_unknown"}),
                               headers={"Stripe-Signature": "sig"})
        assert response.status_code == 200
        assert response.json()["status"] == "processed"


# ─── CONCURRENT DUPLICATE WEBHOOK ───────────────────────────────

@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
class TestConcurrentWebhook:
    @patch("stripe.Webhook.construct_event")
    def test_concurrent_same_event_prevented(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_conc", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1", "active", "price_test_pro")
        )
        payload = json.dumps({"id": "evt_conc"})
        results = []
        for _ in range(5):
            res = client.post("/webhooks/stripe", content=payload,
                              headers={"Stripe-Signature": "sig"})
            results.append(res.json()["status"])
        assert results.count("processed") == 1
        assert results.count("already_processed") == 4
        db = TestSessionLocal()
        try:
            count = db.query(StripeEvent).filter(
                StripeEvent.stripe_event_id == "evt_conc"
            ).count()
            assert count == 1
        finally:
            db.close()


# ─── SUBSCRIPTION STATUS MAPPING ────────────────────────────────

@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
class TestSubscriptionStatusMapping:
    @patch("stripe.Webhook.construct_event")
    def test_incomplete_expired_maps_to_canceled(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_map_1", "customer.subscription.updated",
            make_stripe_subscription("sub_inactive_stripe_1", "cus_inactive_1",
                                     "incomplete_expired", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_map_1"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_inactive_stripe_1"
            ).first()
            assert sub.status == "canceled"
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_trialing_maps_to_active(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_map_2", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1",
                                     "trialing", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_map_2"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_free_stripe_1"
            ).first()
            assert sub.status == "active"
        finally:
            db.close()

    @patch("stripe.Webhook.construct_event")
    def test_unpaid_maps_to_past_due(self, mock_construct, client):
        mock_construct.return_value = make_stripe_event(
            "evt_map_3", "customer.subscription.updated",
            make_stripe_subscription("sub_free_stripe_1", "cus_free_1",
                                     "unpaid", "price_test_pro")
        )
        client.post("/webhooks/stripe", content=json.dumps({"id": "evt_map_3"}),
                     headers={"Stripe-Signature": "sig"})
        db = TestSessionLocal()
        try:
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == "sub_free_stripe_1"
            ).first()
            assert sub.status == "past_due"
        finally:
            db.close()
