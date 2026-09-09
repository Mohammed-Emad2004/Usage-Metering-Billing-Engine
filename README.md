# FlyRank Internship Backend Track Capstone: Usage Metering & Billing Engine

Production-ready backend capstone implementing usage metering, quota enforcement, integer-only cost calculation, and idempotent event tracking with FastAPI, PostgreSQL, SQLAlchemy, Alembic, and Stripe.

---

## CURRENT IMPLEMENTATION STATUS

### Phase 1 — Design & Project Foundation (Complete)
- Clean layered project structure (`app/`, `alembic/`, `tests/`, `docs/`)
- Database models (`Tenant`, `Plan`, `Subscription`, `UsageEvent`) with tenant isolation and idempotency uniqueness constraints
- Alembic migration setup
- FastAPI application skeleton with `GET /health` and config management (`pydantic-settings`)
- Docker Compose configuration for PostgreSQL
- Comprehensive documentation
- Initial unit/API tests for health checks

### Phase 2 — Core Billing Logic (Complete)
- Idempotent usage tracking via `POST /generate` with `Idempotency-Key` header
- Database-level duplicate prevention (`UNIQUE(tenant_id, idempotency_key)`)
- Quota enforcement against tenant subscription plan limits
- Clear 429/402 semantics (429 = quota exceeded, 402 = payment/subscription required)
- Usage retrieval via `GET /usage` with per-tenant monthly aggregation
- Service layer architecture (QuotaService, MeterService) with repository pattern
- 22 deterministic integration tests against PostgreSQL
- Monthly usage aggregation (current month only, not historical)

### Phase 3 — Stripe Integration (Complete)
- Stripe Checkout integration (`POST /billing/checkout`) — creates Stripe Checkout sessions for plan upgrades
- Stripe Webhook endpoint (`POST /webhooks/stripe`) — receives and processes Stripe events
- HMAC-SHA256 webhook signature verification with timestamp tolerance
- Database-level event deduplication via `StripeEvent` model with `UNIQUE(stripe_event_id)`
- Savepoint-based idempotency for webhook event recording
- Three webhook event handlers:
  - `checkout.session.completed` — upgrades free tenants to Pro, stores Stripe customer/subscription IDs
  - `customer.subscription.updated` — synchronizes subscription status and plan from Stripe
  - `customer.subscription.deleted` — marks subscription as canceled
- Stripe status mapping (trialing→active, unpaid→past_due, incomplete_expired→canceled, etc.)
- Production guard: rejects placeholder Stripe secrets with 503
- Customer ID reuse: existing Stripe customers are reused, not recreated
- 28 deterministic integration tests covering checkout, signature verification, all webhook handlers, idempotency, and status mapping

### Phase 4 — Cost & Finalization (Complete)
- Integer-only cost calculation engine (`app/services/cost.py`)
- Pricing constants centralized in `app/config.py` (integer cents, per-1K token rates)
- Token sub-category breakdown: input, cached input, output, reasoning tokens
- `POST /generate` accepts optional token breakdown (backward-compatible)
- `GET /usage` returns `cost` per usage type and `total_cost`
- Cached input tokens priced cheaper than normal input tokens
- Reasoning tokens billed at output-token rate
- Floor-division rounding for deterministic integer arithmetic
- Alembic migration `003_token_breakdown` adding token columns to `usage_events`
- 62 new tests (32 unit + 18 API integration + 12 validation/idempotency) covering all cost edge cases

### Planned for Later Phases
- Invoices, proration, overage billing

---

## Core Requirements & Tech Stack

- **Python 3.10+** + **FastAPI**
- **PostgreSQL** via Docker Compose (or local installation)
- **SQLAlchemy 2.0** + **Alembic**
- **Pytest** + **HTTPX**
- **Stripe Test Mode + Stripe CLI**
- **Strict rule**: Money stored as integers (cents / micro-units), never floats.
- **Strict rule**: Stripe secrets pinned to `.env`, never committed.

---

## Quota Limits

### Free Plan
- **1,000** API calls / month
- **100,000** AI tokens / month

### Pro Plan
- **50,000** API calls / month
- **5,000,000** AI tokens / month

---

## API Endpoints

### POST /generate

Records a billable usage event. Requires an `Idempotency-Key` header that must match the `idempotency_key` in the request body.

**Headers:**
```
Idempotency-Key: <unique-key>
Content-Type: application/json
```

**Request Body:**
```json
{
    "tenant_id": "tenant_123",
    "usage_type": "api_calls",
    "quantity": 1,
    "idempotency_key": "unique-request-key"
}
```

For `ai_tokens`, you can optionally include a token breakdown:
```json
{
    "tenant_id": "tenant_123",
    "usage_type": "ai_tokens",
    "quantity": 1000,
    "idempotency_key": "unique-request-key",
    "input_tokens": 600,
    "cached_input_tokens": 100,
    "output_tokens": 200,
    "reasoning_tokens": 100
}
```

The breakdown must sum to `quantity`. If omitted, all tokens are treated as input tokens.

- `usage_type`: One of `"api_calls"` or `"ai_tokens"`
- `quantity`: Positive integer (must be > 0)

**Response (201 Created):**
```json
{
    "event_id": "evt_abc123",
    "tenant_id": "tenant_123",
    "usage_type": "api_calls",
    "quantity": 1,
    "idempotency_key": "unique-request-key",
    "created_at": "2026-08-30 12:00:00+00:00",
    "status": "recorded"
}
```

**Idempotent Retry (same tenant + key):**
```json
{
    "event_id": "evt_abc123",
    "status": "reused",
    ...
}
```

**Error Responses:**
- `404` — Tenant not found
- `402` — No subscription, or subscription is past_due/canceled
- `429` — Usage quota exceeded for the current billing period
- `422` — Validation error (invalid quantity, missing fields, etc.)
- `400` — Idempotency-Key header does not match body

### GET /usage

Returns current-month usage and plan limits for a tenant.

**Query Parameters:**
- `tenant_id` (required)

**Example:** `GET /usage?tenant_id=tenant_123`

**Response (200 OK):**
```json
{
    "tenant_id": "tenant_123",
    "plan_id": "free",
    "subscription_status": "active",
    "api_calls": {
        "used": 42,
        "limit": 1000,
        "cost": 42
    },
    "ai_tokens": {
        "used": 15000,
        "limit": 100000,
        "cost": 45
    },
    "total_cost": 87
}
```

Cost is calculated in integer cents using per-category pricing:
- API calls: 1 cent per call
- Input tokens: 3 cents per 1,000 tokens
- Cached input tokens: 1 cent per 1,000 tokens (cheaper)
- Output tokens: 15 cents per 1,000 tokens
- Reasoning tokens: 15 cents per 1,000 tokens (same as output)

**Error Responses:**
- `404` — Tenant not found
- `402` — No valid subscription/plan

### POST /billing/checkout

Creates a Stripe Checkout session for upgrading to the Pro plan.

**Request Body:**
```json
{
    "tenant_id": "tenant_123"
}
```

**Response (201 Created):**
```json
{
    "checkout_url": "https://checkout.stripe.com/...",
    "session_id": "cs_test_...",
    "tenant_id": "tenant_123"
}
```

**Error Responses:**
- `404` — Tenant not found
- `400` — Tenant is already on the Pro plan
- `402` — Tenant has no subscription
- `503` — Stripe is not configured

### POST /webhooks/stripe

Receives Stripe webhook events. Requires a valid `Stripe-Signature` header.

**Headers:**
```
Stripe-Signature: t=<timestamp>,v1=<hmac-signature>
Content-Type: application/json
```

**Response (200 OK):**
```json
{"status": "processed"}
```
Or for duplicate events:
```json
{"status": "already_processed"}
```

**Error Responses:**
- `400` — Invalid webhook signature
- `503` — Webhook secret not configured

---

## Idempotency Behavior

The system guarantees **exactly-once** usage recording per `(tenant_id, idempotency_key)` pair:

1. First request with a given key: creates a usage event, returns `status: "recorded"`
2. Subsequent requests with the same key: returns the original event, `status: "reused"`
3. The duplicate does **not** consume additional quota
4. Different tenants may use the same idempotency key independently
5. The PostgreSQL `UNIQUE(tenant_id, idempotency_key)` constraint is the concurrency safety mechanism

**To demonstrate:**
```bash
# First request — recorded
curl -X POST http://localhost:8000/generate \
  -H "Idempotency-Key: demo-key-1" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant_free_1","usage_type":"api_calls","quantity":1,"idempotency_key":"demo-key-1"}'

# Second request — reused, same event_id, usage unchanged
curl -X POST http://localhost:8000/generate \
  -H "Idempotency-Key: demo-key-1" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant_free_1","usage_type":"api_calls","quantity":1,"idempotency_key":"demo-key-1"}'
```

---

## Quota Enforcement

Before recording usage, the system checks:

```
current_month_usage + requested_quantity <= plan_limit
```

- **Below limit**: Request succeeds (201)
- **Exactly at limit**: Request succeeds (201) — the boundary is inclusive
- **Would exceed limit**: Request rejected with 429

Usage is calculated per tenant, per usage type, for the current calendar month (UTC).

---

## 429 vs 402 Semantics

| Code | Meaning | When |
|------|---------|------|
| **429** Too Many Requests | Usage quota exceeded | `current_usage + requested > plan_limit` |
| **402** Payment Required | Subscription/payment issue | No subscription, or subscription status is `past_due` or `canceled` |

The 429 response includes a machine-readable detail:
```json
{
    "detail": {
        "error": "Usage quota exceeded",
        "usage_type": "api_calls",
        "current_usage": 1000,
        "requested_quantity": 1,
        "limit": 1000,
        "reason": "Request would cross monthly limit of 1000 for api_calls."
    }
}
```

---

## Local Setup & Quickstart

### 1. Create and Activate Virtual Environment
```bash
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On macOS/Linux:
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and fill in local database credentials:
```bash
cp .env.example .env
```

### 4. Start PostgreSQL via Docker Compose
```bash
docker-compose up -d
```

### 5. Run Alembic Migrations
```bash
alembic upgrade head
```

### 6. Seed Plans
```bash
python -m app.db.seed
```

### 7. Start FastAPI Development Server
```bash
uvicorn app.main:app --reload
```

### 8. Run Tests
```bash
pytest -v
```

---

## Demonstrating Quota Boundary

The test plan uses small limits for fast verification:

| Test Tenant | Plan | API Call Limit | AI Token Limit |
|---|---|---|---|
| `tenant_free_1` | Free | 10 | 100 |
| `tenant_pro_1` | Pro | 1,000 | 10,000 |

**To demonstrate over-quota rejection:**
```bash
# Fill the quota (10 API calls)
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:8000/generate \
    -H "Idempotency-Key: fill-$i" \
    -H "Content-Type: application/json" \
    -d "{\"tenant_id\":\"tenant_free_1\",\"usage_type\":\"api_calls\",\"quantity\":1,\"idempotency_key\":\"fill-$i\"}"
done

# This should return 429
curl -s -X POST http://localhost:8000/generate \
  -H "Idempotency-Key: exceed-1" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"tenant_free_1","usage_type":"api_calls","quantity":1,"idempotency_key":"exceed-1"}'
```

---

## Project Structure

```
app/
├── api/routes/
│   ├── health.py          # GET /health
│   ├── metering.py        # POST /generate, GET /usage
│   ├── billing.py         # POST /billing/checkout
│   └── webhooks.py        # POST /webhooks/stripe
├── config.py              # Settings + pricing constants
├── db/
│   ├── database.py        # Engine, SessionLocal, Base, get_db
│   ├── models/
│   │   ├── tenant.py
│   │   ├── plan.py
│   │   ├── subscription.py
│   │   ├── usage_event.py  # UNIQUE(tenant_id, idempotency_key) + token breakdown
│   │   └── stripe_event.py # UNIQUE(stripe_event_id)
│   └── seed.py            # Seeds Free and Pro plans
├── repositories/
│   └── __init__.py        # TenantRepo, SubscriptionRepo, UsageRepo
├── schemas/
│   ├── billing.py         # CheckoutRequest, CheckoutResponse
│   ├── generate.py        # GenerateRequest (with token breakdown), GenerateResponse
│   ├── usage.py           # UsageType enum
│   └── usage_response.py  # TenantUsageResponse, UsageMetricDetail (with cost)
├── services/
│   ├── __init__.py        # QuotaService, MeterService
│   ├── cost.py            # CostCalculator (integer-only, pure)
│   └── stripe.py          # StripeService (Checkout, Webhook, Event dedup)
└── main.py                # FastAPI app
tests/
├── conftest.py            # PostgreSQL test fixtures + Stripe helpers
├── api/
│   ├── test_health.py     # Phase 1 health tests (2)
│   ├── test_metering.py   # Phase 2 integration tests (22)
│   ├── test_billing.py    # Phase 3 Stripe tests (28)
│   └── test_cost.py       # Phase 4 API cost tests (18)
└── unit/
    └── test_cost.py       # Phase 4 cost engine unit tests (32)
```
