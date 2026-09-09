#!/usr/bin/env python3
"""
FlyRank Capstone -- Final Demo Script (Phase 5)

Runs a self-contained, reproducible demo covering all five capstone requirements:
  1. Quota boundary behavior
  2. Idempotency / retry protection
  3. Stripe Free -> Pro upgrade (mocked webhook)
  4. Forged webhook rejection + duplicate replay
  5. Final /usage + pricing verification

Uses FastAPI TestClient (no live server required).
Stripe calls are mocked -- no real Stripe credentials needed.

Usage:
    python -m demo.run_demo          # from project root
"""
import sys, os, json, hashlib, hmac, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.db.models import Tenant, Plan, Subscription, UsageEvent, StripeEvent
from app.services.stripe import StripeService

TEST_DATABASE_URL = "postgresql://postgres@localhost:5432/flyrank_metering"
test_engine = create_engine(TEST_DATABASE_URL, poolclass=StaticPool,
                            connect_args={"options": "-csearch_path=public"})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

TEST_WEBHOOK_SECRET = "whsec_demo_secret_for_hmac_signing"


def _sign(payload, secret, ts=None):
    if ts is None:
        ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _mock_stripe_event(event_id, event_type, data_object):
    m = MagicMock()
    m.id = event_id
    m.type = event_type
    m.data.object = data_object
    return m


def _checkout_data(tenant_id, customer_id, subscription_id):
    return {
        "customer": customer_id,
        "subscription": subscription_id,
        "metadata": {"tenant_id": tenant_id},
        "subscription_details": {},
    }


def _sub_data(sub_id, cust_id, status, price_id):
    return {
        "id": sub_id, "customer": cust_id, "status": status,
        "items": {"data": [{"price": {"id": price_id}}]},
    }


DIVIDER = "=" * 60


def step(title):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def subsection(title):
    print(f"\n--- {title} ---")


def db_count(table, **filters):
    db = TestSessionLocal()
    try:
        q = db.query(table)
        for k, v in filters.items():
            q = q.filter(getattr(table, k) == v)
        return q.count()
    finally:
        db.close()


def db_get_usage_event(tenant_id, idempotency_key):
    db = TestSessionLocal()
    try:
        return db.query(UsageEvent).filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == idempotency_key,
        ).first()
    finally:
        db.close()


def db_get_subscription(tenant_id):
    db = TestSessionLocal()
    try:
        return db.query(Subscription).filter(Subscription.tenant_id == tenant_id).first()
    finally:
        db.close()


def pp_json(data, indent=2):
    print(json.dumps(data, indent=indent, default=str))


def run_demo():
    # Drop ALL tables in public schema (including alembic_version not in Base.metadata)
    # then drop orphaned PostgreSQL custom types, then recreate from ORM models.
    with test_engine.connect() as conn:
        conn.execute(text(
            "DO $$ DECLARE r RECORD; BEGIN "
            "FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP "
            "EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE'; "
            "END LOOP; "
            "FOR r IN (SELECT typname FROM pg_type WHERE typnamespace = 'public'::regnamespace "
            "AND typtype = 'c') LOOP "
            "EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(r.typname) || ' CASCADE'; "
            "END LOOP; END $$;"
        ))
        conn.commit()
    Base.metadata.create_all(bind=test_engine)
    db = TestSessionLocal()
    try:
        # Plans using same IDs as the Stripe handler expects ("free" / "pro")
        # Small limits for human-readable demo
        db.add(Plan(id="free", name="Demo Free", api_call_limit=10, ai_token_limit=100))
        db.add(Plan(id="pro", name="Demo Pro", api_call_limit=1000, ai_token_limit=10000))
        db.add(Tenant(id="demo_free", name="Demo Free Tenant"))
        db.add(Subscription(id="sub_demo_free", tenant_id="demo_free", plan_id="free",
                            status="active"))
        db.add(Tenant(id="demo_pro", name="Demo Pro Tenant"))
        db.add(Subscription(id="sub_demo_pro", tenant_id="demo_pro", plan_id="pro",
                            status="active"))
        db.commit()
    finally:
        db.close()

    client = TestClient(app)

    print("\n" + "#" * 60)
    print("  FlyRank Usage Metering & Billing Engine -- Final Demo")
    print("#" * 60)
    print(f"\nDemo tenants seeded: demo_free (Free, api_limit=10, ai_limit=100)")
    print(f"                     demo_pro  (Pro,  api_limit=1000, ai_limit=10000)")

    # ============================================================
    #  DEMO STEP 1 -- Quota Boundary
    # ============================================================
    step("DEMO STEP 1 -- Quota Boundary Behavior")

    subsection("1a. Tenant below quota (0/10)")
    r = client.get("/usage?tenant_id=demo_free")
    pp_json(r.json())

    subsection("1b. Fill quota -- 10 API calls (10/10)")
    for i in range(10):
        r = client.post("/generate", json={
            "tenant_id": "demo_free", "usage_type": "api_calls",
            "quantity": 1, "idempotency_key": f"fill-{i}"
        }, headers={"Idempotency-Key": f"fill-{i}"})
        assert r.status_code == 201, f"Expected 201 on fill-{i}, got {r.status_code}"

    r = client.get("/usage?tenant_id=demo_free")
    usage = r.json()
    print(f"  Used: {usage['api_calls']['used']}/{usage['api_calls']['limit']}")
    print(f"  Cost: {usage['api_calls']['cost']} cents")
    pp_json(usage)

    subsection("1c. Over-quota request -> 429")
    r = client.post("/generate", json={
        "tenant_id": "demo_free", "usage_type": "api_calls",
        "quantity": 1, "idempotency_key": "exceed-1"
    }, headers={"Idempotency-Key": "exceed-1"})
    print(f"  HTTP Status: {r.status_code}")
    assert r.status_code == 429
    pp_json(r.json())

    subsection("1d. Verify rejected request created no usage event")
    ev = db_get_usage_event("demo_free", "exceed-1")
    print(f"  Event in DB: {ev}")
    assert ev is None, "FAIL: rejected request created a usage event!"
    print("  PASS: Rejected request did NOT create a usage event.")

    # ============================================================
    #  DEMO STEP 2 -- Idempotency / Retry Protection
    # ============================================================
    step("DEMO STEP 2 -- Idempotency / Retry Protection")

    subsection("2a. First request (recorded) -- using ai_tokens (quota still available)")
    payload = {
        "tenant_id": "demo_free", "usage_type": "ai_tokens",
        "quantity": 50, "idempotency_key": "idem-demo-1"
    }
    r1 = client.post("/generate", json=payload, headers={"Idempotency-Key": "idem-demo-1"})
    pp_json(r1.json())
    assert r1.json()["status"] == "recorded"
    event_id_1 = r1.json()["event_id"]

    subsection("2b. Same request retried (reused)")
    r2 = client.post("/generate", json=payload, headers={"Idempotency-Key": "idem-demo-1"})
    pp_json(r2.json())
    assert r2.json()["status"] == "reused"
    assert r2.json()["event_id"] == event_id_1, "FAIL: event_id mismatch!"

    subsection("2c. Verify in database -- exactly 1 row")
    ev = db_get_usage_event("demo_free", "idem-demo-1")
    print(f"  DB row: id={ev.id}, quantity={ev.quantity}, created_at={ev.created_at}")
    count = db_count(UsageEvent, tenant_id="demo_free", idempotency_key="idem-demo-1")
    print(f"  Row count for this key: {count}")
    assert count == 1
    print("  PASS: Exactly 1 usage event in database.")

    # ============================================================
    #  DEMO STEP 3 -- Stripe Free -> Pro Upgrade
    # ============================================================
    step("DEMO STEP 3 -- Stripe Free -> Pro Upgrade")

    subsection("3a. Show current subscription state (Free)")
    sub_before = db_get_subscription("demo_free")
    print(f"  plan_id={sub_before.plan_id}, status={sub_before.status}")
    print(f"  stripe_customer_id={sub_before.stripe_customer_id}")

    subsection("3b. Simulate Stripe Checkout webhook -> checkout.session.completed")
    with patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        with patch("stripe.Webhook.construct_event") as mock_construct:
            mock_construct.return_value = _mock_stripe_event(
                "evt_demo_upgrade", "checkout.session.completed",
                _checkout_data("demo_free", "cus_demo_new", "sub_demo_stripe_new"),
            )
            r = client.post("/webhooks/stripe", content=json.dumps({"id": "evt_demo_upgrade"}),
                            headers={"Stripe-Signature": "sig"})
            print(f"  Webhook response: {r.status_code} {r.json()}")

    subsection("3c. Verify subscription upgraded to Pro")
    sub_after = db_get_subscription("demo_free")
    print(f"  plan_id={sub_after.plan_id}  (was: {sub_before.plan_id})")
    print(f"  status={sub_after.status}")
    print(f"  stripe_customer_id={sub_after.stripe_customer_id}")
    print(f"  stripe_subscription_id={sub_after.stripe_subscription_id}")
    assert sub_after.plan_id == "pro", "FAIL: plan_id not upgraded!"
    assert sub_after.status == "active"
    print("  PASS: Free -> Pro upgrade verified.")

    subsection("3d. GET /usage -- new Pro limits visible")
    r = client.get("/usage?tenant_id=demo_free")
    pp_json(r.json())
    assert r.json()["api_calls"]["limit"] == 1000
    assert r.json()["ai_tokens"]["limit"] == 10000
    print("  PASS: Pro limits (1000/10000) now visible.")

    # ============================================================
    #  DEMO STEP 4 -- Forged Webhook + Replay Protection
    # ============================================================
    step("DEMO STEP 4 -- Security: Forged Webhook + Replay Protection")

    subsection("4a. Forged webhook -> 400")
    with patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        forged_payload = b'{"id":"evt_forged","type":"checkout.session.completed","data":{"object":{}}}'
        wrong_sig = _sign(b'{"id":"evt_different_payload"}', TEST_WEBHOOK_SECRET)
        r = client.post("/webhooks/stripe", content=forged_payload,
                        headers={"Stripe-Signature": wrong_sig})
        print(f"  HTTP Status: {r.status_code}")
        print(f"  Response: {r.json()}")
        assert r.status_code == 400
        print("  PASS: Forged webhook rejected with 400.")

    subsection("4b. Verify no state mutation from forged webhook")
    count_sevt = db_count(StripeEvent, stripe_event_id="evt_forged")
    print(f"  StripeEvent records for evt_forged: {count_sevt}")
    assert count_sevt == 0
    sub_check = db_get_subscription("demo_free")
    print(f"  Subscription unchanged: plan_id={sub_check.plan_id}")
    print("  PASS: No state mutation from forged webhook.")

    subsection("4c. Duplicate webhook replay -> already_processed")
    with patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET):
        with patch("stripe.Webhook.construct_event") as mock_construct:
            mock_construct.return_value = _mock_stripe_event(
                "evt_demo_replay", "customer.subscription.updated",
                _sub_data("sub_demo_stripe_new", "cus_demo_new", "active", "price_test"),
            )
            r1 = client.post("/webhooks/stripe", content=json.dumps({"id": "evt_demo_replay"}),
                             headers={"Stripe-Signature": "sig"})
            print(f"  First delivery:  {r1.json()}")
            assert r1.json()["status"] == "processed"

            r2 = client.post("/webhooks/stripe", content=json.dumps({"id": "evt_demo_replay"}),
                             headers={"Stripe-Signature": "sig"})
            print(f"  Second delivery: {r2.json()}")
            assert r2.json()["status"] == "already_processed"
            print("  PASS: Duplicate webhook ignored.")

    # ============================================================
    #  DEMO STEP 5 -- Final Accounting + Pricing Proof
    # ============================================================
    step("DEMO STEP 5 -- Final Accounting + Pricing Verification")

    subsection("5a. Generate AI token usage with breakdown")
    r = client.post("/generate", json={
        "tenant_id": "demo_free", "usage_type": "ai_tokens",
        "quantity": 3000, "idempotency_key": "demo-ai-1",
        "input_tokens": 1000, "cached_input_tokens": 500,
        "output_tokens": 1000, "reasoning_tokens": 500,
    }, headers={"Idempotency-Key": "demo-ai-1"})
    assert r.status_code == 201
    print(f"  Recorded: {r.json()['quantity']} AI tokens with breakdown")

    subsection("5b. Final GET /usage -- complete accounting")
    r = client.get("/usage?tenant_id=demo_free")
    usage = r.json()
    pp_json(usage)

    subsection("5c. Pricing verification")
    # api_calls: 10 calls * 1 cent = 10 cents
    # ai_tokens: idempotency step=50 (cost=0), breakdown step:
    #   input=1000*3//1000=3, cached=500*1//1000=0, output=1000*15//1000=15, reasoning=500*15//1000=7 => 25
    # total = 10 + 25 = 35
    print(f"  API calls used:   {usage['api_calls']['used']}")
    print(f"  API calls limit:  {usage['api_calls']['limit']}")
    print(f"  API calls cost:   {usage['api_calls']['cost']} cents (expected: 10)")
    print(f"  AI tokens used:   {usage['ai_tokens']['used']}")
    print(f"  AI tokens limit:  {usage['ai_tokens']['limit']}")
    print(f"  AI tokens cost:   {usage['ai_tokens']['cost']} cents (expected: 25)")
    print(f"  Total cost:       {usage['total_cost']} cents (expected: 35)")

    assert usage["api_calls"]["cost"] == 10, f"FAIL: api_cost={usage['api_calls']['cost']}"
    assert usage["ai_tokens"]["cost"] == 25, f"FAIL: ai_cost={usage['ai_tokens']['cost']}"
    assert usage["total_cost"] == 35, f"FAIL: total={usage['total_cost']}"
    print("  PASS: All cost calculations correct.")

    # -- Summary --
    step("DEMO COMPLETE -- ALL CHECKS PASSED")
    print("""
  Summary:
    1. Quota boundary:      PASS -- 10/10 filled, 11th rejected (429)
    2. Idempotency retry:   PASS -- recorded/reused, 1 DB row, counted once
    3. Stripe upgrade:      PASS -- Free->Pro via webhook, limits updated
    4. Forged webhook:      PASS -- 400, no state mutation
    5. Duplicate replay:    PASS -- already_processed, ignored
    6. Final accounting:    PASS -- used/limit/cost match pricing rules

  Pricing summary (all integer cents, floor division):
    API calls:  10 calls x 1 cent/call = 10 cents
    AI tokens:  input=3, cached=0, output=15, reasoning=7 = 25 cents
    Total: 35 cents

  "Usage, money, and customer access stay correct under
   retries, failures, and real-world conditions."
""")

    Base.metadata.drop_all(bind=test_engine)


if __name__ == "__main__":
    run_demo()
