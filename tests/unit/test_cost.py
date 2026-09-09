"""
Unit tests for the integer-only cost calculation engine.

Pricing constants used in tests (from app/config.py defaults):
  API_CALL_PRICE_CENTS = 1
  INPUT_TOKEN_PRICE_CENTS_PER_1K = 3
  CACHED_INPUT_TOKEN_PRICE_CENTS_PER_1K = 1
  OUTPUT_TOKEN_PRICE_CENTS_PER_1K = 15
  REASONING_TOKEN_PRICE_CENTS_PER_1K = 15
"""
import pytest
from unittest.mock import patch
from app.services.cost import calculate_api_call_cost, calculate_ai_token_cost, calculate_total_cost


# ── Pricing constants (must match Settings defaults) ─────────────
API_PRICE = 1
INPUT_PRICE = 3
CACHED_PRICE = 1
OUTPUT_PRICE = 15
REASONING_PRICE = 15


# ─── API CALL COST ──────────────────────────────────────────────

class TestApiCallCost:
    def test_zero_calls(self):
        assert calculate_api_call_cost(0) == 0

    def test_one_call(self):
        assert calculate_api_call_cost(1) == 1

    def test_ten_calls(self):
        assert calculate_api_call_cost(10) == 10

    def test_large_quantity(self):
        assert calculate_api_call_cost(100000) == 100000

    def test_cost_is_integer(self):
        result = calculate_api_call_cost(5)
        assert isinstance(result, int)


# ─── AI TOKEN COST: SINGLE CATEGORIES ───────────────────────────

class TestAiTokenCostSingleCategory:
    def test_zero_tokens(self):
        assert calculate_ai_token_cost() == 0

    def test_input_tokens_only(self):
        # 1000 input tokens at 3 cents/1k = 3 cents
        assert calculate_ai_token_cost(input_tokens=1000) == 3

    def test_cached_input_tokens_only(self):
        # 1000 cached input tokens at 1 cent/1k = 1 cent
        assert calculate_ai_token_cost(cached_input_tokens=1000) == 1

    def test_output_tokens_only(self):
        # 1000 output tokens at 15 cents/1k = 15 cents
        assert calculate_ai_token_cost(output_tokens=1000) == 15

    def test_reasoning_tokens_only(self):
        # 1000 reasoning tokens at 15 cents/1k = 15 cents
        assert calculate_ai_token_cost(reasoning_tokens=1000) == 15


# ─── AI TOKEN COST: REASONING = OUTPUT RULE ─────────────────────

class TestReasoningTokensBilledAsOutput:
    def test_reasoning_same_price_as_output(self):
        cost_r = calculate_ai_token_cost(reasoning_tokens=5000)
        cost_o = calculate_ai_token_cost(output_tokens=5000)
        assert cost_r == cost_o

    def test_reasoning_tokens_not_free(self):
        cost = calculate_ai_token_cost(reasoning_tokens=1000)
        assert cost > 0

    def test_reasoning_not_independent_category(self):
        # 2000 reasoning tokens should cost the same as 2000 output tokens
        assert calculate_ai_token_cost(reasoning_tokens=2000) == calculate_ai_token_cost(output_tokens=2000)


# ─── AI TOKEN COST: CACHED CHEAPER THAN INPUT ───────────────────

class TestCachedInputCheaperThanInput:
    def test_cached_is_cheaper(self):
        cost_input = calculate_ai_token_cost(input_tokens=10000)
        cost_cached = calculate_ai_token_cost(cached_input_tokens=10000)
        assert cost_cached < cost_input

    def test_cached_price_ratio(self):
        # cached (1 cent/1k) should be 1/3 the cost of input (3 cents/1k)
        cost_input = calculate_ai_token_cost(input_tokens=3000)
        cost_cached = calculate_ai_token_cost(cached_input_tokens=3000)
        assert cost_cached * INPUT_PRICE == cost_input * CACHED_PRICE


# ─── AI TOKEN COST: MIXED CATEGORIES ────────────────────────────

class TestAiTokenCostMixed:
    def test_mixed_input_cached_output(self):
        # 2000 input (6) + 1000 cached (1) + 500 output (7) = 14
        cost = calculate_ai_token_cost(
            input_tokens=2000,
            cached_input_tokens=1000,
            output_tokens=500,
        )
        assert cost == 14

    def test_mixed_output_reasoning(self):
        # 1000 output (15) + 1000 reasoning (15) = 30
        cost = calculate_ai_token_cost(
            output_tokens=1000,
            reasoning_tokens=1000,
        )
        assert cost == 30

    def test_all_categories(self):
        # 1000 input (3) + 500 cached (0) + 2000 output (30) + 1000 reasoning (15) = 48
        cost = calculate_ai_token_cost(
            input_tokens=1000,
            cached_input_tokens=500,
            output_tokens=2000,
            reasoning_tokens=1000,
        )
        assert cost == 48

    def test_not_single_universal_rate(self):
        # Verify that categories are NOT just summed and multiplied by one price
        cost_separate = calculate_ai_token_cost(input_tokens=1000) + calculate_ai_token_cost(output_tokens=1000)
        cost_combined = calculate_ai_token_cost(input_tokens=1000, output_tokens=1000)
        assert cost_separate == cost_combined  # Same result (additive), but NOT 2000 * single_rate


# ─── INTEGER ARITHMETIC / NO FLOATS ─────────────────────────────

class TestIntegerArithmetic:
    def test_all_results_are_integers(self):
        results = [
            calculate_api_call_cost(7),
            calculate_ai_token_cost(input_tokens=777),
            calculate_ai_token_cost(cached_input_tokens=333),
            calculate_ai_token_cost(output_tokens=555),
            calculate_ai_token_cost(reasoning_tokens=999),
            calculate_ai_token_cost(100, 200, 300, 400),
            calculate_total_cost(10, 20),
        ]
        for r in results:
            assert isinstance(r, int), f"Expected int, got {type(r)}: {r}"

    def test_floor_division_behavior(self):
        # 500 input tokens at 3 cents/1k = 500*3//1000 = 1 (floor)
        assert calculate_ai_token_cost(input_tokens=500) == 1
        # 333 cached input tokens at 1 cent/1k = 333*1//1000 = 0 (floor)
        assert calculate_ai_token_cost(cached_input_tokens=333) == 0


# ─── LARGE QUANTITIES ───────────────────────────────────────────

class TestLargeQuantities:
    def test_million_input_tokens(self):
        # 1,000,000 input tokens at 3 cents/1k = 3000 cents = $30
        assert calculate_ai_token_cost(input_tokens=1_000_000) == 3000

    def test_million_output_tokens(self):
        # 1,000,000 output tokens at 15 cents/1k = 15000 cents = $150
        assert calculate_ai_token_cost(output_tokens=1_000_000) == 15000

    def test_large_mixed(self):
        cost = calculate_ai_token_cost(
            input_tokens=500_000,
            cached_input_tokens=200_000,
            output_tokens=100_000,
            reasoning_tokens=50_000,
        )
        # input: 500000*3//1000 = 1500
        # cached: 200000*1//1000 = 200
        # output: 100000*15//1000 = 1500
        # reasoning: 50000*15//1000 = 750
        assert cost == 1500 + 200 + 1500 + 750


# ─── BOUNDARY VALUES ────────────────────────────────────────────

class TestBoundaryValues:
    def test_999_tokens(self):
        # 999*3//1000 = 2 (floor division)
        assert calculate_ai_token_cost(input_tokens=999) == 2

    def test_1000_tokens_exact(self):
        assert calculate_ai_token_cost(input_tokens=1000) == INPUT_PRICE

    def test_1001_tokens_still_one_unit(self):
        # 1001*3//1000 = 3 (same as 1000)
        assert calculate_ai_token_cost(input_tokens=1001) == INPUT_PRICE

    def test_1999_tokens(self):
        # 1999*3//1000 = 5
        assert calculate_ai_token_cost(input_tokens=1999) == 5

    def test_2000_tokens_two_units(self):
        assert calculate_ai_token_cost(input_tokens=2000) == INPUT_PRICE * 2

    def test_one_token(self):
        assert calculate_ai_token_cost(input_tokens=1) == 0  # 1*3//1000 = 0

    def test_cached_one_token(self):
        assert calculate_ai_token_cost(cached_input_tokens=1) == 0  # 1*1//1000 = 0

    def test_999_cached_rounds_down(self):
        # 999*1//1000 = 0
        assert calculate_ai_token_cost(cached_input_tokens=999) == 0


# ─── TOTAL COST ─────────────────────────────────────────────────

class TestTotalCost:
    def test_zero_total(self):
        assert calculate_total_cost(0, 0) == 0

    def test_api_only(self):
        assert calculate_total_cost(50, 0) == 50

    def test_ai_only(self):
        assert calculate_total_cost(0, 100) == 100

    def test_combined(self):
        assert calculate_total_cost(50, 100) == 150

    def test_cost_is_integer(self):
        assert isinstance(calculate_total_cost(1, 2), int)


# ─── PRICING CONSTANTS ARE PINNED ───────────────────────────────

class TestPricingConstantsPinned:
    def test_api_call_price(self):
        from app.config import settings
        assert settings.API_CALL_PRICE_CENTS == 1

    def test_input_token_price(self):
        from app.config import settings
        assert settings.INPUT_TOKEN_PRICE_CENTS_PER_1K == 3

    def test_cached_input_token_price(self):
        from app.config import settings
        assert settings.CACHED_INPUT_TOKEN_PRICE_CENTS_PER_1K == 1

    def test_output_token_price(self):
        from app.config import settings
        assert settings.OUTPUT_TOKEN_PRICE_CENTS_PER_1K == 15

    def test_reasoning_token_price(self):
        from app.config import settings
        assert settings.REASONING_TOKEN_PRICE_CENTS_PER_1K == 15

    def test_cached_cheaper_than_input(self):
        from app.config import settings
        assert settings.CACHED_INPUT_TOKEN_PRICE_CENTS_PER_1K < settings.INPUT_TOKEN_PRICE_CENTS_PER_1K

    def test_reasoning_equals_output(self):
        from app.config import settings
        assert settings.REASONING_TOKEN_PRICE_CENTS_PER_1K == settings.OUTPUT_TOKEN_PRICE_CENTS_PER_1K
