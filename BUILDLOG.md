# Build Log: FlyRank Usage Metering & Billing Engine

## Phase 1: Design & Project Foundation

- **Date**: August 29, 2026
- **AI Assistance Used For**:
  - Project structure scaffolding and layered architecture organization.
  - Database schema design (`tenants`, `plans`, `subscriptions`, `usage_events`) with composite uniqueness constraints for robust idempotency.
  - Architecture documentation detailing quota enforcement, integer-only cost calculation, and Stripe webhook synchronization.
  - Configuration management setup (`pydantic-settings`) and FastAPI application routing.

---

## Phase 2: Core Billing Logic

- **Date**: August 30, 2026
- **What Was Implemented**:
  - `POST /generate` — Dummy billable endpoint with idempotency header enforcement
  - `GET /usage` — Per-tenant usage retrieval with plan limits
  - `MeterService.record()` — Idempotent usage recording with IntegrityError-based concurrency safety
  - `QuotaService.check_quota()` — Quota enforcement reading limits from tenant's subscription plan
  - `UsageRepository` — create, get_by_tenant_and_key, get_current_month_usage
  - `TenantRepository`, `SubscriptionRepository` — lookup methods
  - Pydantic schemas: `GenerateRequest`, `GenerateResponse`, `UsageType`, `TenantUsageResponse`, `UsageMetricDetail`
  - 22 integration tests against PostgreSQL covering all Phase 2 requirements (A-J)
  - `tests/conftest.py` with PostgreSQL-backed test fixtures and automatic table creation/teardown

- **Key Design Decisions**:
  - **Idempotency check before quota check**: A retry of an already-recorded request must return the existing event, not a 429. This prevents false rejections when a client retries after network timeout.
  - **UNIQUE constraint as concurrency safety**: The `UNIQUE(tenant_id, idempotency_key)` constraint is the final defense against duplicates. The service catches `IntegrityError` and retrieves the existing event.
  - **Test isolation via create_all/drop_all**: Each test creates fresh PostgreSQL tables, seeds test data, and drops tables after. This handles `db.commit()` in service code cleanly without transaction interference.
  - **429 vs 402 distinction**: 429 = usage quota exceeded (ordinary rate exhaustion). 402 = subscription/payment issue (no subscription, past_due, canceled). This is deterministic and tested.
  - **Monthly aggregation**: Uses `created_at >= start_of_month` (UTC) to scope usage to the current calendar month. Old events from previous months do not count.

- **AI Assistance Used For**:
  - Initial service/repository layer design and Pydantic schema creation
  - Test structure and coverage planning
  - Documentation updates (README, EVIDENCE, BUILDLOG)

- **Incorrect AI Approaches That Were Fixed**:
  - **Initial test file used SQLite in-memory**: The original `test_metering.py` used `sqlite:///:memory:` for tests. This failed because FastAPI's `TestClient` runs endpoint handlers in a separate thread via `run_in_threadpool`, and in-memory SQLite databases are thread-local. The endpoint thread had no access to the test thread's database. **Fix**: Rewrote tests to use PostgreSQL directly with `create_all`/`drop_all` per test.
  - **Idempotency check after quota check**: The original `MeterService.record()` checked quota first, then idempotency. This caused retries of successful requests to fail with 429 if the quota was subsequently filled. **Fix**: Moved the idempotency check before the quota check so retries always succeed.

- **Test/Debugging Discoveries**:
  - PostgreSQL 18 was installed locally but required password authentication. Temporarily switched `pg_hba.conf` to trust auth for local development and testing.
  - Alembic logging format errors during `upgrade head` were non-fatal (Python logging format string issues in Alembic), migration completed successfully.
  - FastAPI `TestClient` uses `anyio.to_thread.run_sync` for synchronous endpoint handlers, meaning endpoint code runs in a different thread. This is why in-memory SQLite fails for test isolation.

---

## Phase 3: Stripe Integration

- **Date**: August 30, 2026
- **What Was Implemented**:
  - `POST /billing/checkout` — Creates Stripe Checkout sessions for Pro plan upgrades
  - `POST /webhooks/stripe` — Receives and processes Stripe webhook events
  - `StripeService.verify_webhook_signature()` — HMAC-SHA256 signature verification with timestamp tolerance
  - `StripeService.record_event()` — Savepoint-based idempotency via `StripeEvent` model with `UNIQUE(stripe_event_id)`
  - `StripeService.handle_checkout_completed()` — Upgrades free tenants to Pro, stores Stripe customer/subscription IDs
  - `StripeService.handle_subscription_updated()` — Synchronizes subscription status and plan from Stripe events
  - `StripeService.handle_subscription_deleted()` — Marks subscription as canceled
  - `StripeService.create_checkout_session()` — Customer ID reuse, Stripe Checkout session creation
  - Alembic migration `002_stripe_events` — Adds `stripe_events` table
  - `app/db/models/stripe_event.py` — `StripeEvent` model with unique constraint on `stripe_event_id`
  - `app/schemas/billing.py` — `CheckoutRequest`, `CheckoutResponse` Pydantic schemas
  - `app/api/routes/billing.py` — Checkout endpoint route
  - `app/api/routes/webhooks.py` — Webhook endpoint route
  - 28 integration tests covering checkout, signature verification, all webhook handlers, idempotency, concurrent dedup, and status mapping

- **Key Design Decisions**:
  - **Production guard on placeholder secrets**: The 503 guard on `whsec_placeholder` / `sk_test_placeholder` ensures unconfigured deployments cannot accidentally process real Stripe events. Tests bypass this by patching `settings.STRIPE_WEBHOOK_SECRET` to a non-placeholder value and generating valid HMAC signatures.
  - **Savepoint-based event dedup**: Uses `db.begin_nested()` (SAVEPOINT) to record events. On `IntegrityError` (duplicate `stripe_event_id`), the savepoint is rolled back without affecting the outer transaction. This is cleaner than `db.rollback()` which would discard all pending changes.
  - **Customer ID reuse**: When `stripe_customer_id` already exists on a subscription, checkout reuses it instead of creating a new Stripe customer. This prevents duplicate customer records in Stripe.
  - **Webhook handler commits**: The webhook route commits after all handler logic runs. This ensures event recording and subscription updates are atomically persisted.
  - **Stripe status mapping**: Maps Stripe statuses (`trialing`, `unpaid`, `incomplete_expired`, etc.) to internal statuses (`active`, `past_due`, `canceled`) to maintain a simpler internal state machine.

- **AI Assistance Used For**:
  - Stripe service layer implementation and webhook handler design
  - Test strategy for webhook signature verification (HMAC-SHA256 generation in tests)
  - Fixing test failures: identified that class-level `@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", ...)` was needed alongside `@patch("stripe.Webhook.construct_event")` to bypass the 503 production guard in tests
  - Documentation updates (README, EVIDENCE, BUILDLOG)

- **Incorrect AI Approaches That Were Fixed**:
  - **Tests only mocked `construct_event`, not the webhook secret**: Initial webhook tests only patched `stripe.Webhook.construct_event` but left `settings.STRIPE_WEBHOOK_SECRET` as the placeholder value. The `verify_webhook_signature` method checks the secret before calling `construct_event`, so the 503 guard fired first. **Fix**: Added class-level `@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", "whsec_test_secret_for_hmac_signing")` to all webhook test classes.
  - **Checkout test assertion mismatched reuse behavior**: `test_stripe_customer_mapping_stored` expected `cus_new_789` but the fixture pre-populated `stripe_customer_id="cus_free_1"`, and the code correctly reuses existing IDs. **Fix**: Updated assertion to match the correct behavior (`cus_free_1`).

- **Test/Debugging Discoveries**:
  - `@patch` on a class applies to all methods in that class. Using `@patch("app.config.settings.STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)` as a class decorator patches the attribute on the `Settings` singleton, which is visible to all modules that imported it (including `app.services.stripe`).
  - The `stripe.Webhook.construct_event` mock must return an object with `.id`, `.type`, and `.data.object` attributes — using `MagicMock` with `make_stripe_event()` helper creates the correct structure.
  - Savepoint-based dedup (`db.begin_nested()`) works correctly with FastAPI's dependency injection and PostgreSQL. The `IntegrityError` is caught, the savepoint is rolled back, and the outer transaction remains intact for subsequent operations.

---

## Phase 4: Cost & Finalization

- **Date**: August 30, 2026
- **What Was Implemented**:
  - `app/services/cost.py` — Pure integer-only cost calculator: `calculate_api_call_cost()`, `calculate_ai_token_cost()`, `calculate_total_cost()`
  - `app/config.py` — Pricing constants: `API_CALL_PRICE_CENTS=1`, `INPUT_TOKEN_PRICE_CENTS_PER_1K=3`, `CACHED_INPUT_TOKEN_PRICE_CENTS_PER_1K=1`, `OUTPUT_TOKEN_PRICE_CENTS_PER_1K=15`, `REASONING_TOKEN_PRICE_CENTS_PER_1K=15`
  - Token sub-category columns on `usage_events`: `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens`
  - Alembic migration `003_token_breakdown` — Adds 4 token columns to `usage_events`
  - `GenerateRequest` schema updated with optional token breakdown + `model_validator` ensuring breakdown sums to quantity
  - `UsageMetricDetail` schema extended with `cost: int` field
  - `TenantUsageResponse` schema extended with `total_cost: int` field
  - `UsageRepository.get_current_month_token_breakdown()` — Aggregates token sub-categories for current month
  - `MeterService.record()` — Accepts and stores token breakdown
  - `MeterService.get_tenant_usage()` — Calculates per-category and total cost from stored breakdowns
  - `POST /generate` — Backward-compatible: if no breakdown provided for `ai_tokens`, treats entire quantity as input tokens
  - `GET /usage` — Returns `cost` per usage type and `total_cost`
  - 62 new tests (32 unit + 30 API/integration) covering all cost edge cases

- **Pricing Model (integer cents)**:
  - API calls: 1 cent per call
  - Input tokens: 3 cents per 1,000 tokens
  - Cached input tokens: 1 cent per 1,000 tokens (cheaper than input)
  - Output tokens: 15 cents per 1,000 tokens
  - Reasoning tokens: 15 cents per 1,000 tokens (same rate as output — capstone rule)
  - Floor division (`//`) for truncation

- **Key Design Decisions**:
  - **Integer-only cost engine**: All calculations use Python `int` arithmetic. No floats, no Decimal-through-float. Pricing constants are per-1K tokens to avoid fractional per-token costs.
  - **Pure function design**: `calculate_api_call_cost()`, `calculate_ai_token_cost()`, `calculate_total_cost()` are pure functions with no side effects, independent of DB/HTTP/Stripe.
  - **Backward compatibility**: Existing `POST /generate` calls without token breakdown continue to work. The `model_validator` defaults the entire quantity to input tokens when no breakdown is provided.
  - **Cost calculated from events, not stored**: Monthly cost is computed on-the-fly from the token breakdown stored on each usage event. No redundant monetary state is stored.
  - **Separate token columns, not JSON**: Added `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens` as integer columns rather than a JSON blob, enabling SQL aggregation and type safety.

- **AI Assistance Used For**:
  - Cost engine design and pricing constant selection
  - Test strategy for cost calculation edge cases (boundary values, large quantities, mixed categories)
  - Fixing test failures: identified that free plan's `ai_token_limit=100` caused 429 on large token quantities in API tests — switched tests to use `tenant_pro_1` (limit 10,000)
  - Fixing boundary math: corrected test expectations where `999*3//1000=2` (not 0) due to floor division
  - Documentation updates (README, EVIDENCE, BUILDLOG, architecture)

- **Incorrect AI Approaches That Were Fixed**:
  - **Token breakdown validation too strict**: Initially required `input_tokens + cached_input_tokens + output_tokens + reasoning_tokens == quantity` for ALL `ai_tokens` requests. This broke 2 existing tests that send `ai_tokens` without a breakdown. **Fix**: Made the breakdown optional — if all sub-categories are 0, default `input_tokens = quantity` for backward compatibility.
  - **Boundary test expectations wrong**: Tests assumed `999*3//1000 = 0` and `1999*3//1000 = 3`. Actual results: `999*3//1000 = 2` and `1999*3//1000 = 5`. **Fix**: Corrected test assertions to match actual floor-division arithmetic.
  - **API tests exceeded free plan quota**: Tests using `tenant_free_1` (ai_token_limit=100) tried to record 1000-3000 tokens, triggering 429. **Fix**: Changed tests to use `tenant_pro_1` (ai_token_limit=10,000) for large-quantity tests.

- **Test/Debugging Discoveries**:
  - `model_validator(mode="after")` on Pydantic v2 BaseModel can mutate field values (e.g., setting `input_tokens = quantity` as a default). This is the intended backward-compatibility mechanism.
  - The `get_current_month_token_breakdown()` repository method uses `func.coalesce(func.sum(...), 0)` to handle NULL when no events exist.
  - Token sub-category columns use `server_default=text("0")` in the SQLAlchemy model to ensure existing rows (before migration) get default values.
  - Floor division (`//`) is the standard for billing truncation. For example, 1,500 input tokens at 3 cents/1K = `1500*3//1000 = 4` cents (not 4.5).
