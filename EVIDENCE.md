# Evidence Log

## Phase 1 — Design & Project Foundation

### 1. Project Boots & FastAPI Health Check
- **Command**: `pytest tests/api/test_health.py -v`
- **Status**: Verified / Passing
- **Output Evidence**:
```
tests/api/test_health.py::test_health_check PASSED
tests/api/test_health.py::test_root PASSED
======================== 2 passed, 1 warning in 0.94s =========================
```

### 2. PostgreSQL Configuration & Schema Design Verification
- **Status**: Verified
- **Configuration**: `app/config.py`, `alembic/env.py`, and `docker-compose.yml` configured for PostgreSQL (`postgresql://postgres:postgres@localhost:5432/flyrank_metering`).

---

## Phase 2 — Core Billing Logic

### 1. Successful Billable Request
- **Command**: `POST /generate` with valid tenant, usage_type, quantity, idempotency_key
- **Status**: Verified / Passing
- **Evidence** (from `test_first_request_returns_201`):
```json
{
    "event_id": "evt_...",
    "tenant_id": "tenant_free_1",
    "usage_type": "api_calls",
    "quantity": 2,
    "idempotency_key": "key_001",
    "status": "recorded"
}
```
- **HTTP Status**: 201 Created

### 2. Idempotent Duplicate Request — Exactly One Usage Event
- **Command**: Same `POST /generate` called twice with identical tenant_id + idempotency_key
- **Status**: Verified / Passing
- **Evidence** (from `test_same_tenant_same_key_returns_reused` + `test_duplicate_does_not_create_second_event_in_db`):
  - First request: `status: "recorded"`
  - Second request: `status: "reused"`, same `event_id`
  - Database: exactly 1 row in `usage_events` for that idempotency_key
  - Usage endpoint: counts quantity exactly once

### 3. Same Idempotency Key for Different Tenants
- **Command**: Two different tenants use the same idempotency_key
- **Status**: Verified / Passing
- **Evidence** (from `test_different_tenants_same_key_both_succeed`):
  - Both return 201 with different `event_id` values
  - Each tenant's event is independent

### 4. Invalid Quantity Rejection
- **Command**: `POST /generate` with `quantity: 0` or `quantity: -1`
- **Status**: Verified / Passing
- **Evidence** (from `test_zero_quantity_rejected`, `test_negative_quantity_rejected`):
  - Both return 422 (Pydantic validation error via `Field(..., gt=0)`)

### 5. Invalid/Missing Tenant
- **Command**: `POST /generate` with non-existent `tenant_id`
- **Status**: Verified / Passing
- **Evidence** (from `test_nonexistent_tenant_returns_404`):
  - Returns 404 with message: `"Tenant with ID 'non_existent_tenant' not found."`

### 6. Missing Idempotency Key
- **Command**: `POST /generate` without `Idempotency-Key` header
- **Status**: Verified / Passing
- **Evidence** (from `test_missing_idempotency_key_returns_422`):
  - Returns 422 (FastAPI header validation)

### 7. Usage Below Quota
- **Command**: Request that stays within plan limits
- **Status**: Verified / Passing
- **Evidence** (from `test_usage_within_quota_succeeds`):
  - Returns 201, usage endpoint shows correct cumulative usage

### 8. Usage Exactly at Quota Boundary
- **Command**: Request that fills quota to exactly the limit
- **Status**: Verified / Passing
- **Evidence** (from `test_usage_exactly_at_limit_succeeds`):
  - Free plan limit: 10 API calls
  - Request with quantity=10 succeeds (201)
  - Usage endpoint shows `used: 10, limit: 10`

### 9. Over-Quota Rejection (429)
- **Command**: Request that would exceed the plan limit
- **Status**: Verified / Passing
- **Evidence** (from `test_over_quota_returns_429`):
  - After consuming 10 API calls, the next request returns 429
  - Response detail includes:
    ```json
    {
        "usage_type": "api_calls",
        "current_usage": 10,
        "requested_quantity": 1,
        "limit": 10
    }
    ```

### 10. Rejected Request Does Not Create Usage Event
- **Command**: Over-quota request that is rejected
- **Status**: Verified / Passing
- **Evidence** (from `test_rejected_request_does_not_create_usage_event`):
  - Database query confirms 0 rows for the rejected idempotency_key

### 11. 402 for Inactive Subscription
- **Command**: `POST /generate` with `past_due` subscription
- **Status**: Verified / Passing
- **Evidence** (from `test_past_due_subscription_returns_402`):
  - Returns 402 Payment Required

### 12. 402 for Missing Subscription
- **Command**: `POST /generate` for tenant with no subscription
- **Status**: Verified / Passing
- **Evidence** (from `test_tenant_without_subscription_returns_402`):
  - Returns 402 Payment Required

### 13. Monthly Aggregation — Current Month Only
- **Command**: Create old-month event via DB, verify it is not counted
- **Status**: Verified / Passing
- **Evidence** (from `test_old_month_events_not_counted`):
  - Inserted event with `created_at` 35 days ago
  - `GET /usage` shows `used: 0` for that tenant

### 14. GET /usage Returns Correct Structure
- **Command**: `GET /usage?tenant_id=tenant_free_1`
- **Status**: Verified / Passing
- **Evidence** (from `test_usage_returns_all_fields`, `test_pro_plan_usage_limits`):
  - Free plan: `api_calls.limit: 10, ai_tokens.limit: 100`
  - Pro plan: `api_calls.limit: 1000, ai_tokens.limit: 10000`

### 15. Concurrent/Idempotency Stress Test
- **Command**: 5 sequential requests with identical tenant_id + idempotency_key
- **Status**: Verified / Passing
- **Evidence** (from `test_database_constraint_prevents_duplicate`):
  - Exactly 1 `recorded`, 4 `reused`
  - All return the same `event_id`
  - Database contains exactly 1 row

### 16. Full Test Suite Output
- **Command**: `pytest -v`
- **Status**: All 24 tests passing
- **Output**:
```
tests/api/test_health.py::test_health_check PASSED
tests/api/test_health.py::test_root PASSED
tests/api/test_metering.py::TestFirstUsageRequestSucceeds::test_first_request_returns_201 PASSED
tests/api/test_metering.py::TestIdempotentDuplicateRequest::test_same_tenant_same_key_returns_reused PASSED
tests/api/test_metering.py::TestIdempotentDuplicateRequest::test_duplicate_does_not_create_second_event_in_db PASSED
tests/api/test_metering.py::TestSameKeyDifferentTenants::test_different_tenants_same_key_both_succeed PASSED
tests/api/test_metering.py::TestInvalidQuantity::test_zero_quantity_rejected PASSED
tests/api/test_metering.py::TestInvalidQuantity::test_negative_quantity_rejected PASSED
tests/api/test_metering.py::TestInvalidTenant::test_nonexistent_tenant_returns_404 PASSED
tests/api/test_metering.py::TestInvalidTenant::test_missing_idempotency_key_returns_422 PASSED
tests/api/test_metering.py::TestInvalidTenant::test_usage_endpoint_nonexistent_tenant_returns_404 PASSED
tests/api/test_metering.py::TestUsageBelowQuota::test_usage_within_quota_succeeds PASSED
tests/api/test_metering.py::TestUsageExactlyAtQuota::test_usage_exactly_at_limit_succeeds PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_over_quota_returns_429 PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_rejected_request_does_not_create_usage_event PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_different_usage_type_within_quota_succeeds PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_ai_tokens_over_quota_returns_429 PASSED
tests/api/test_metering.py::TestMonthlyAggregation::test_current_month_events_count PASSED
tests/api/test_metering.py::TestMonthlyAggregation::test_old_month_events_not_counted PASSED
tests/api/test_metering.py::TestInactiveSubscriptionRejected::test_past_due_subscription_returns_402 PASSED
tests/api/test_metering.py::TestNoSubscriptionReturns402::test_tenant_without_subscription_returns_402 PASSED
tests/api/test_metering.py::TestUsageReadAPI::test_usage_returns_all_fields PASSED
tests/api/test_metering.py::TestUsageReadAPI::test_pro_plan_usage_limits PASSED
tests/api/test_metering.py::TestConcurrencyIdempotency::test_database_constraint_prevents_duplicate PASSED
======================== 24 passed, 1 warning in 2.34s =========================
```

---

## Phase 3 — Stripe Integration

### 1. Checkout Creates Stripe Checkout Session
- **Command**: `POST /billing/checkout` with valid `tenant_id`
- **Status**: Verified / Passing
- **Evidence** (from `test_existing_tenant_creates_checkout`):
  - Returns 201 with `checkout_url`, `session_id`, `tenant_id`
  - Stripe `checkout.sessions.create` called with `mode="subscription"` and configured price ID

### 2. Checkout Reuses Existing Stripe Customer
- **Command**: Second checkout call for same tenant
- **Status**: Verified / Passing
- **Evidence** (from `test_reuses_existing_stripe_customer`):
  - `customers.create` is NOT called when `stripe_customer_id` already exists
  - Existing customer ID is passed to checkout session

### 3. Checkout Returns 400 for Existing Pro Tenant
- **Command**: `POST /billing/checkout` for tenant already on Pro plan
- **Status**: Verified / Passing
- **Evidence** (from `test_already_pro_tenant_returns_400`):
  - Returns 400 with message: `"already on the Pro plan"`

### 4. Valid HMAC Signature Accepted
- **Command**: `verify_webhook_signature` with correctly signed payload
- **Status**: Verified / Passing
- **Evidence** (from `test_valid_signature_accepted`):
  - HMAC-SHA256 signature with timestamp verification
  - Returns decoded Stripe event object

### 5. Forged/Wrong Signature Rejected (400)
- **Command**: `verify_webhook_signature` with incorrect signature
- **Status**: Verified / Passing
- **Evidence** (from `test_forged_signature_returns_400`):
  - Returns 400 with message: `"Invalid webhook signature."`
  - No database mutations occur

### 6. Missing Webhook Secret Returns 503
- **Command**: `verify_webhook_signature` when `STRIPE_WEBHOOK_SECRET` is placeholder
- **Status**: Verified / Passing
- **Evidence** (from `test_missing_secret_returns_503`):
  - Returns 503: production guard prevents processing with unconfigured secrets

### 7. checkout.session.completed — Upgrades Free to Pro
- **Command**: Webhook event for new checkout completion
- **Status**: Verified / Passing
- **Evidence** (from `test_upgrades_free_to_pro`):
  - Subscription `plan_id` changes from `"free"` to `"pro"`
  - `stripe_customer_id` and `stripe_subscription_id` are stored
  - Status set to `"active"`

### 8. customer.subscription.updated — Status Synchronization
- **Command**: Webhook event with `status: "active"` from Stripe
- **Status**: Verified / Passing
- **Evidence** (from `test_active_subscription_synchronizes`):
  - Plan ID mapped to `"pro"` (matching Stripe price ID)
  - Status correctly synchronized
  - Period start/end timestamps stored

### 9. customer.subscription.updated — past_due Mapping
- **Command**: Webhook event with `status: "past_due"`
- **Status**: Verified / Passing
- **Evidence** (from `test_past_due_synchronizes`):
  - Internal status set to `"past_due"`

### 10. customer.subscription.deleted — Marks Canceled
- **Command**: Webhook event for subscription cancellation
- **Status**: Verified / Passing
- **Evidence** (from `test_subscription_becomes_canceled`):
  - Subscription status set to `"canceled"`
  - Tenant record and usage history remain intact

### 11. Webhook Idempotency — Duplicate Event Rejected
- **Command**: Same Stripe event sent twice
- **Status**: Verified / Passing
- **Evidence** (from `test_same_event_twice_processed_once`):
  - First request: `{"status": "processed"}`
  - Second request: `{"status": "already_processed"}`
  - Database contains exactly 1 `StripeEvent` record

### 12. Concurrent Duplicate Prevention
- **Command**: 5 sequential requests with identical event ID
- **Status**: Verified / Passing
- **Evidence** (from `test_concurrent_same_event_prevented`):
  - Exactly 1 `processed`, 4 `already_processed`
  - Database: 1 `StripeEvent` record

### 13. Stripe Status Mapping — All Variants
- **Command**: Webhook events with various Stripe statuses
- **Status**: Verified / Passing
- **Evidence** (from status mapping tests):
  - `incomplete_expired` → `"canceled"`
  - `trialing` → `"active"`
  - `unpaid` → `"past_due"`

### 14. Unknown Event Type — Ignored Safely
- **Command**: Webhook event with unrecognized `event.type`
- **Status**: Verified / Passing
- **Evidence** (from `test_unknown_event_ignored_safely`):
  - Returns 200 with `{"status": "processed"}`
  - No state changes

### 15. Full Test Suite Output (Phase 3)
- **Command**: `pytest -v`
- **Status**: All 52 tests passing
- **Output**:
```
tests/api/test_billing.py::TestCheckoutEndpoint::test_existing_tenant_creates_checkout PASSED
tests/api/test_billing.py::TestCheckoutEndpoint::test_missing_tenant_returns_404 PASSED
tests/api/test_billing.py::TestCheckoutEndpoint::test_configured_pro_price_is_used PASSED
tests/api/test_billing.py::TestCheckoutEndpoint::test_stripe_customer_mapping_stored PASSED
tests/api/test_billing.py::TestCheckoutEndpoint::test_already_pro_tenant_returns_400 PASSED
tests/api/test_billing.py::TestCheckoutEndpoint::test_no_subscription_tenant_returns_402 PASSED
tests/api/test_billing.py::TestCheckoutEndpoint::test_reuses_existing_stripe_customer PASSED
tests/api/test_billing.py::TestWebhookSignature::test_valid_signature_accepted PASSED
tests/api/test_billing.py::TestWebhookSignature::test_forged_signature_returns_400 PASSED
tests/api/test_billing.py::TestWebhookSignature::test_invalid_signature_no_db_mutation PASSED
tests/api/test_billing.py::TestWebhookSignature::test_missing_secret_returns_503 PASSED
tests/api/test_billing.py::TestCheckoutSessionCompleted::test_upgrades_free_to_pro PASSED
tests/api/test_billing.py::TestCheckoutSessionCompleted::test_stripe_customer_id_stored PASSED
tests/api/test_billing.py::TestCheckoutSessionCompleted::test_stripe_subscription_id_stored PASSED
tests/api/test_billing.py::TestSubscriptionUpdated::test_active_subscription_synchronizes PASSED
tests/api/test_billing.py::TestSubscriptionUpdated::test_past_due_synchronizes PASSED
tests/api/test_billing.py::TestSubscriptionUpdated::test_plan_synchronizes_to_pro PASSED
tests/api/test_billing.py::TestSubscriptionDeleted::test_subscription_becomes_canceled PASSED
tests/api/test_billing.py::TestSubscriptionDeleted::test_tenant_remains_intact PASSED
tests/api/test_billing.py::TestSubscriptionDeleted::test_usage_history_remains_intact PASSED
tests/api/test_billing.py::TestWebhookIdempotency::test_same_event_twice_processed_once PASSED
tests/api/test_billing.py::TestWebhookIdempotency::test_database_contains_one_stripe_event_record PASSED
tests/api/test_billing.py::TestWebhookIdempotency::test_subscription_state_not_corrupted PASSED
tests/api/test_billing.py::TestUnknownEventType::test_unknown_event_ignored_safely PASSED
tests/api/test_billing.py::TestConcurrentWebhook::test_concurrent_same_event_prevented PASSED
tests/api/test_billing.py::TestSubscriptionStatusMapping::test_incomplete_expired_maps_to_canceled PASSED
tests/api/test_billing.py::TestSubscriptionStatusMapping::test_trialing_maps_to_active PASSED
tests/api/test_billing.py::TestSubscriptionStatusMapping::test_unpaid_maps_to_past_due PASSED
tests/api/test_health.py::test_health_check PASSED
tests/api/test_health.py::test_root PASSED
tests/api/test_metering.py::TestFirstUsageRequestSucceeds::test_first_request_returns_201 PASSED
tests/api/test_metering.py::TestIdempotentDuplicateRequest::test_same_tenant_same_key_returns_reused PASSED
tests/api/test_metering.py::TestIdempotentDuplicateRequest::test_duplicate_does_not_create_second_event_in_db PASSED
tests/api/test_metering.py::TestSameKeyDifferentTenants::test_different_tenants_same_key_both_succeed PASSED
tests/api/test_metering.py::TestInvalidQuantity::test_zero_quantity_rejected PASSED
tests/api/test_metering.py::TestInvalidQuantity::test_negative_quantity_rejected PASSED
tests/api/test_metering.py::TestInvalidTenant::test_nonexistent_tenant_returns_404 PASSED
tests/api/test_metering.py::TestInvalidTenant::test_missing_idempotency_key_returns_422 PASSED
tests/api/test_metering.py::TestInvalidTenant::test_usage_endpoint_nonexistent_tenant_returns_404 PASSED
tests/api/test_metering.py::TestUsageBelowQuota::test_usage_within_quota_succeeds PASSED
tests/api/test_metering.py::TestUsageExactlyAtQuota::test_usage_exactly_at_limit_succeeds PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_over_quota_returns_429 PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_rejected_request_does_not_create_usage_event PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_different_usage_type_within_quota_succeeds PASSED
tests/api/test_metering.py::TestUsageExceedingQuota::test_ai_tokens_over_quota_returns_429 PASSED
tests/api/test_metering.py::TestMonthlyAggregation::test_current_month_events_count PASSED
tests/api/test_metering.py::TestMonthlyAggregation::test_old_month_events_not_counted PASSED
tests/api/test_metering.py::TestInactiveSubscriptionRejected::test_past_due_subscription_returns_402 PASSED
tests/api/test_metering.py::TestNoSubscriptionReturns402::test_tenant_without_subscription_returns_402 PASSED
tests/api/test_metering.py::TestUsageReadAPI::test_usage_returns_all_fields PASSED
tests/api/test_metering.py::TestUsageReadAPI::test_pro_plan_usage_limits PASSED
tests/api/test_metering.py::TestConcurrencyIdempotency::test_database_constraint_prevents_duplicate PASSED
======================= 52 passed in 4.29s =========================
```

---

## Phase 4 — Cost & Finalization

### 1. Zero Usage → Zero Cost
- **Command**: `GET /usage?tenant_id=tenant_free_1` (no events recorded)
- **Status**: Verified / Passing
- **Evidence** (from `test_zero_usage_zero_cost`):
```json
{
    "api_calls": {"used": 0, "limit": 10, "cost": 0},
    "ai_tokens": {"used": 0, "limit": 100, "cost": 0},
    "total_cost": 0
}
```

### 2. API Call Cost Calculation
- **Command**: Record 5 API calls, then `GET /usage`
- **Status**: Verified / Passing
- **Evidence** (from `test_api_call_cost_calculation`):
  - 5 calls × 1 cent/call = 5 cents
  - `api_calls.cost: 5`, `total_cost: 5`

### 3. AI Tokens Without Breakdown → Treated as Input
- **Command**: `POST /generate` with `ai_tokens` and no sub-category breakdown
- **Status**: Verified / Passing
- **Evidence** (from `test_ai_tokens_without_breakdown_defaults_to_input`):
  - 3,000 tokens (no breakdown) → treated as input tokens
  - 3,000 × 3 cents/1K = 9 cents
  - `ai_tokens.cost: 9`

### 4. Cached Input Cheaper Than Normal Input
- **Command**: Compare cost of 10,000 input vs 10,000 cached input tokens
- **Status**: Verified / Passing
- **Evidence** (from `test_cached_is_cheaper`):
  - Input: 10,000 × 3/1K = 30 cents
  - Cached: 10,000 × 1/1K = 10 cents
  - `cost_cached < cost_input`

### 5. Reasoning Tokens Billed as Output Tokens
- **Command**: Compare cost of 5,000 reasoning vs 5,000 output tokens
- **Status**: Verified / Passing
- **Evidence** (from `test_reasoning_same_price_as_output`):
  - Reasoning: 5,000 × 15/1K = 75 cents
  - Output: 5,000 × 15/1K = 75 cents
  - `cost_reasoning == cost_output`

### 6. Reasoning Tokens Not Free
- **Command**: Calculate cost of 1,000 reasoning tokens
- **Status**: Verified / Passing
- **Evidence** (from `test_reasoning_tokens_not_free`):
  - 1,000 × 15/1K = 15 cents (> 0)

### 7. Mixed Token Categories Independently Priced
- **Command**: 1,000 input + 1,000 cached + 1,000 output + 500 reasoning
- **Status**: Verified / Passing
- **Evidence** (from `test_mixed_token_types_cost`):
  - input: 1000 × 3/1K = 3
  - cached: 1000 × 1/1K = 1
  - output: 1000 × 15/1K = 15
  - reasoning: 500 × 15/1K = 7
  - Total: 26 cents

### 8. Total Cost Sums API and AI
- **Command**: 3 API calls + 1,000 output tokens
- **Status**: Verified / Passing
- **Evidence** (from `test_total_cost_sums_api_and_ai`):
  - API: 3 × 1 = 3 cents
  - AI: 1000 × 15/1K = 15 cents
  - `total_cost: 18`

### 9. Token Breakdown Validation
- **Command**: `POST /generate` with breakdown not summing to quantity
- **Status**: Verified / Passing
- **Evidence** (from `test_breakdown_not_matching_quantity_rejected`):
  - quantity=1000, input_tokens=500 → 422 Unprocessable Entity

### 10. Idempotent Reuse Does Not Double Cost
- **Command**: Same `POST /generate` sent twice with token breakdown
- **Status**: Verified / Passing
- **Evidence** (from `test_idempotent_reuse_does_not_double_cost`):
  - First: `status: "recorded"`, Second: `status: "reused"`
  - `ai_tokens.used: 3000`, `ai_tokens.cost: 9` (not doubled)

### 11. Existing Metering Behavior Unchanged
- **Command**: All 52 pre-Phase-4 tests
- **Status**: Verified / Passing
- **Evidence**: 0 regressions, all 52 original tests pass

### 12. Full Test Suite Output (Phase 4)
- **Command**: `pytest -v`
- **Status**: All 114 tests passing
- **Test count**: 52 original + 62 new = 114 total
- **Breakdown**:
  - `tests/unit/test_cost.py`: 32 tests (cost engine unit tests)
  - `tests/api/test_cost.py`: 18 tests (API cost integration tests)
  - `tests/api/test_billing.py`: 28 tests (Phase 3)
  - `tests/api/test_metering.py`: 22 tests (Phase 2)
  - `tests/api/test_health.py`: 2 tests (Phase 1)
  - `tests/api/test_cost.py` (validation/idempotency): 12 tests
- **Output**:
```
======================= 114 passed in 5.99s =========================
```

---

## Phase 4 Final Audit

### 1. Full Test Suite
- **Command**: `pytest -v`
- **Status**: 114 passed, 0 failed, 0 skipped
- **Verified**: All unit tests, API integration tests, validation tests, and idempotency tests pass

### 2. Alembic Migration Chain
- **Status**: Verified
- **Chain**: `001_initial` → `002_stripe_events` → `003_token_breakdown`
- **Schema matches models**: `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens` columns present on `usage_events` table

### 3. Integer-Only Cost Engine
- **Status**: Verified
- **Findings**: All cost functions in `app/services/cost.py` use `int` parameters and return `int`. No floats, no Decimal. Floor division (`//`) used throughout. Pricing constants are all `int`.

### 4. Cost Calculation Edge Cases
- **Status**: Verified via 32 unit tests
- **Coverage**: Zero tokens → 0 cost; sub-1K tokens → 0 cost (floor division); boundary values (999, 1000, 1500); exact multiples; mixed categories; large quantities

### 5. Token Breakdown Validation
- **Status**: Verified
- **Findings**: `GenerateRequest.model_validator` enforces breakdown_sum == quantity when breakdown is provided. When no breakdown given (sum=0), entire quantity defaults to input tokens (backward compatibility). Negative values rejected by `ge=0` constraint.

### 6. Idempotency + Cost
- **Status**: Verified
- **Findings**: Idempotency check occurs before quota check in `MeterService.record()`. Reused events return `"reused"` status without creating duplicates. `test_idempotent_reuse_does_not_double_cost` confirms cost not double-counted.

### 7. Quota/Billing Semantics
- **Status**: Verified
- **Findings**: Within quota → 201; over quota → 429; missing subscription → 402; past_due → 402; canceled → 402. Monthly aggregation uses `created_at >= start_of_month` (UTC).

### 8. Stripe Regression
- **Status**: Verified
- **Findings**: All 28 Phase 3 billing tests pass. Checkout session creation, webhook processing, signature verification, and event deduplication all unaffected by Phase 4 changes.

### 9. Documentation Consistency
- **Status**: Verified
- **Findings**: Pricing constants match across `app/config.py`, `docs/architecture.md`, `README.md`, `EVIDENCE.md`, `BUILDLOG.md`. Historical Phase 1 scope in `docs/architecture.md` updated to reflect completed phases.

### 10. Security Audit
- **Status**: Verified
- **Findings**: `.env` is git-ignored. No real secrets in committed files. Only placeholder Stripe keys. HMAC-SHA256 signature verification on webhooks. Production guard rejects placeholder secrets with 503.

### 11. Code Quality
- **Status**: Verified
- **Findings**: No unused imports introduced by Phase 4. Pre-existing unused imports (e.g., `settings` in main.py) are harmless. No print statements in API paths. No SQLite in production code. No float arithmetic in cost paths.

### 12. API Smoke Test
- **Status**: Verified
- **Findings**: Health check -> 200. POST /generate api_calls -> 201. POST /generate ai_tokens -> 201. GET /usage returns correct costs. Idempotency retry returns reused. Cost not doubled after retry.

---

## Phase 5 -- Demo Preparation

### 1. Full Test Suite (Post Phase 5)
- **Command**: `pytest -v`
- **Status**: 114 passed, 0 failed, 0 skipped
- **Output**:
```
======================= 114 passed in 7.36s ========================
```

### 2. Demo Rehearsal -- All Five Steps
- **Command**: `python -m demo.run_demo`
- **Status**: All 6 checks PASS

#### Demo After Pytest (No DB Cleanup)
- **Command**: `pytest` then `python -m demo.run_demo` (sequential, same DB)
- **Status**: PASS -- demo cleanup handles PostgreSQL type conflicts left by test suite

#### Step 1: Quota Boundary
- **Setup**: `demo_free` tenant on Free plan (api_call_limit=10, ai_token_limit=100)
- **Sequence**: Demo fills quota to exact boundary (10/10 API calls), then 11th request rejected
- **HTTP Status**: 429 Too Many Requests
- **Response**:
```json
{
  "detail": {
    "error": "Usage quota exceeded",
    "usage_type": "api_calls",
    "current_usage": 10,
    "requested_quantity": 1,
    "limit": 10,
    "reason": "Request would cross monthly limit of 10 for api_calls."
  }
}
```
- **Rejected request creates no event**: PASS (DB query returns None)

#### Step 2: Idempotency / Retry Protection
- **First request** (ai_tokens, quantity=50): `status: "recorded"`, `event_id: "evt_..."`
- **Second request** (same tenant, same key): `status: "reused"`, same `event_id`
- **Database**: Exactly 1 row in `usage_events` for this idempotency_key
- **Usage counted once**: PASS

#### Step 3: Stripe Free -> Pro Upgrade
- **Before**: `plan_id=free`, `api_calls.limit=10`, `ai_tokens.limit=100`
- **Webhook**: `checkout.session.completed` with `tenant_id=demo_free`
- **After**: `plan_id=pro`, `api_calls.limit=1000`, `ai_tokens.limit=10000`
- **Stripe IDs stored**: `stripe_customer_id=cus_demo_new`, `stripe_subscription_id=sub_demo_stripe_new`
- **GET /usage confirms new limits**: PASS

#### Step 4: Forged Webhook + Replay Protection
- **Forged webhook**: HTTP 400, `{"detail": "Invalid webhook signature."}`
- **No state mutation**: StripeEvent count=0, subscription unchanged
- **Duplicate replay**: First -> `processed`, Second -> `already_processed`
- **PASS**: Both forged rejection and replay protection verified

#### Step 5: Final Accounting + Pricing Verification
- **AI tokens with breakdown**: input=1000, cached=500, output=1000, reasoning=500
- **GET /usage**:
```json
{
  "api_calls": {"used": 10, "limit": 1000, "cost": 10},
  "ai_tokens": {"used": 3050, "limit": 10000, "cost": 25},
  "total_cost": 35
}
```
- **Pricing math** (integer cents, floor division):
  - API calls: 10 x 1 = 10 cents
  - Input: 1000 x 3 // 1000 = 3
  - Cached: 500 x 1 // 1000 = 0
  - Output: 1000 x 15 // 1000 = 15
  - Reasoning: 500 x 15 // 1000 = 7
  - AI total: 25 cents
  - Grand total: 35 cents
- **PASS**: All assertions pass

### 3. Demo Files Created
- `demo/__init__.py` -- Package marker
- `demo/seed_demo.py` -- Deterministic seed for demo tenants (plans + tenants + subscriptions)
- `demo/run_demo.py` -- Self-contained demo runner (TestClient, mocked Stripe, 5 steps)

### 4. Demo Readiness Audit

| Demo Requirement | Status | Evidence |
|---|---|---|
| Demo tenant with deterministic limits | PASS | demo_free on Free plan (api=10, ai=100); demo fills to exact quota |
| Exact quota boundary | PASS | 10/10 filled, used=10, limit=10 |
| Over-quota -> 429 | PASS | 429 with current_usage=10, limit=10 |
| Rejected request creates no event | PASS | DB query returns None for rejected key |
| Idempotency retry | PASS | recorded -> reused, same event_id |
| Exactly one usage event | PASS | DB count=1 for idempotency_key |
| Stripe Free -> Pro | PASS | plan_id changed free -> pro, limits updated |
| Webhook signature verification | PASS | Forged sig -> 400 |
| Forged webhook -> 400 | PASS | HTTP 400, no DB mutation |
| Duplicate webhook ignored | PASS | processed -> already_processed |
| GET /usage correct | PASS | used/limit/cost/total_cost all correct |
| Pricing tests green | PASS | 114 tests all pass |
| Full test suite green | PASS | 114 passed, 0 failed, 0 skipped |
| Git working tree clean | PASS | Phase 5 committed (20e9a20); working tree clean |
