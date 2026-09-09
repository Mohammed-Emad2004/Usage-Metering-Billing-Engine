# Architecture & Design: FlyRank Usage Metering & Billing Engine

## 1. System Overview

The **FlyRank Usage Metering & Billing Engine** is a robust, production-style backend system designed to track API calls and simulated AI token usage per tenant, enforce monthly quotas, calculate costs using integer-only arithmetic (cents/micro-units), and synchronize subscription states securely via Stripe Webhooks.

### Core Architecture Layers

```
 HTTP / API (FastAPI)
         ↓
Services / Business Logic (MeterService, QuotaService, CostService, StripeService)
         ↓
Repositories (Data Access Abstraction)
         ↓
SQLAlchemy ORM
         ↓
PostgreSQL Database
```

---

## 2. Database Schema Design

The system revolves around four core tables with strict relational integrity and isolation:

1. **`tenants`**: Represents customers/organizations.
   - `id` (PK, String/UUID)
   - `name` (String)
   - `created_at` (DateTime)

2. **`plans`**: Defines pricing tiers and hard usage limits.
   - `id` (PK, String)
   - `name` (String, e.g., `free`, `pro`)
   - `api_call_limit` (Integer)
   - `ai_token_limit` (Integer)
   - `created_at` (DateTime)

3. **`subscriptions`**: Links a tenant to their active plan and Stripe metadata.
   - `id` (PK, String)
   - `tenant_id` (FK to `tenants.id`, Unique)
   - `plan_id` (FK to `plans.id`)
   - `stripe_customer_id` (String, Unique, Nullable)
   - `stripe_subscription_id` (String, Unique, Nullable)
   - `status` (String: `active`, `past_due`, `canceled`, `trialing`)
   - `current_period_start` / `current_period_end` (DateTime)
   - `created_at` / `updated_at` (DateTime)

4. **`usage_events`**: Immutable ledger of billable usage actions.
   - `id` (PK, String)
   - `tenant_id` (FK to `tenants.id`)
   - `usage_type` (String: `api_calls`, `ai_tokens`)
   - `quantity` (Integer)
   - `idempotency_key` (String)
   - `created_at` (DateTime)
   - **Database-Level Protection**: `UNIQUE (tenant_id, idempotency_key)` constraint ensures zero duplicate counting under concurrent retried requests.

---

## 3. Idempotency Strategy & Concurrency Protection

Metered billing requires absolute protection against double-counting caused by network timeouts, client retries, or concurrent request dispatch.

### Mechanism
- Clients pass an `Idempotency-Key` header with every billable action (`POST /generate`).
- The database enforces a composite unique constraint on `(tenant_id, idempotency_key)`.
- When `MeterService.record()` attempts to insert a usage event:
  1. If the key is novel, the row is inserted successfully.
  2. If a concurrent or retried request arrives with the same key, PostgreSQL raises a unique constraint violation.
  3. The service catches this integrity error, retrieves the existing record, and returns the original result safely without incrementing usage twice.

---

## 4. Quota Enforcement Algorithm

Before any billable request is serviced:
1. **Current Period Aggregation**: Sum `quantity` from `usage_events` for the tenant within the current billing cycle.
2. **Limit Comparison**:
   - `current_usage + requested_quantity <= plan_limit` $\rightarrow$ **Allow** (HTTP 200/201).
   - `current_usage + requested_quantity > plan_limit` $\rightarrow$ **Reject** with `HTTP 429 Too Many Requests`.
3. **Subscription Status Check**: If the subscription status is `past_due` or `canceled`, reject with `HTTP 402 Payment Required`.

---

## 5. Cost Calculation Design (Integer-Only)

Money must **never** use floating-point numbers due to rounding inaccuracies. All costs are stored and calculated in integer cents.

### Monetary Unit
- **Integer cents** — all cost values are Python `int`.
- Token prices are defined **per 1,000 tokens** to avoid fractional per-token costs.
- Floor division (`//`) is used for truncation (standard billing behavior).

### Pricing Constants (pinned in `app/config.py`)
| Category | Rate | Unit |
|---|---|---|
| API Calls | 1 | cent per call |
| Input Tokens | 3 | cents per 1,000 tokens |
| Cached Input Tokens | 1 | cent per 1,000 tokens (cheaper) |
| Output Tokens | 15 | cents per 1,000 tokens |
| Reasoning Tokens | 15 | cents per 1,000 tokens (same as output) |

### Semantic Rules
- **Cached input tokens** are cheaper than normal input tokens.
- **Reasoning tokens** are billed using the output-token pricing rate.
- Each category is priced independently — they are NOT summed and multiplied by a single rate.

### Cost Calculation Flow
```
Usage Events (current month)
     ↓
Monthly Rollup (per category)
     ↓
Cost Calculator (per-category integer arithmetic)
     ↓
{ used, limit, cost } per usage type + total_cost
```

### API Layer
- `GET /usage` returns `used`, `limit`, `cost` per usage type, plus `total_cost`.
- `POST /generate` accepts optional token sub-category breakdown for `ai_tokens`.
- Backward compatible: if no breakdown is provided, the entire quantity is treated as input tokens.

---

## 6. Stripe Integration Design

- **Source of Truth**: Stripe manages payment methods, checkout sessions, and subscription lifecycles.
- **Local Mirror**: The local database mirrors Stripe state via verified webhooks (`POST /webhooks/stripe`).
- **Webhook Security**: Signatures are cryptographically verified using `STRIPE_WEBHOOK_SECRET`. Invalid signatures return `HTTP 400`.
- **Event Deduplication**: Incoming Stripe event IDs are tracked to ignore duplicate webhook deliveries safely.

---

## 7. Historical Scope Notes

- **Phase 1 (Initial)**: The original Phase 1 scope was limited to project foundation, database models, Alembic configuration, FastAPI skeleton, `/health` endpoint, and core architectural documentation. Metering, Stripe Checkout, webhook event processing, and cost calculation were all deferred to subsequent phases.
- **Phase 2**: Implemented usage metering (`POST /generate`), quota enforcement, `GET /usage`, and idempotent event tracking.
- **Phase 3**: Implemented Stripe Checkout, webhook signature verification, event deduplication, and subscription synchronization.
- **Phase 4**: Implemented integer-only cost calculation with token category breakdown (input, cached input, output, reasoning).
- **Remaining Stretch Goals**: Invoices, proration, overage billing (not implemented; explicitly identified as stretch goals in the capstone).
