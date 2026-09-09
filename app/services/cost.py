"""
Integer-only cost calculator for usage metering.

Monetary unit: integer cents. Token prices are per 1,000 tokens.
All arithmetic is pure integer — no floats, no Decimal-through-float.

Pricing rules (pinned, tested):
  - API calls: flat rate per call
  - Input tokens: rate per 1,000
  - Cached input tokens: cheaper rate per 1,000
  - Output tokens: rate per 1,000
  - Reasoning tokens: same rate as output tokens (capstone rule)
"""

from app.config import settings


def calculate_api_call_cost(num_calls: int) -> int:
    """Return cost in integer cents for the given number of API calls."""
    return num_calls * settings.API_CALL_PRICE_CENTS


def calculate_ai_token_cost(
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> int:
    """Return cost in integer cents for the given token breakdown.

    Each category is priced independently at its own rate.
    Floor division is used (standard billing truncation).
    Reasoning tokens are priced identically to output tokens.
    """
    cost = (
        input_tokens * settings.INPUT_TOKEN_PRICE_CENTS_PER_1K // 1000
        + cached_input_tokens * settings.CACHED_INPUT_TOKEN_PRICE_CENTS_PER_1K // 1000
        + output_tokens * settings.OUTPUT_TOKEN_PRICE_CENTS_PER_1K // 1000
        + reasoning_tokens * settings.REASONING_TOKEN_PRICE_CENTS_PER_1K // 1000
    )
    return cost


def calculate_total_cost(api_call_cost: int, ai_token_cost: int) -> int:
    """Return total monthly cost in integer cents."""
    return api_call_cost + ai_token_cost
