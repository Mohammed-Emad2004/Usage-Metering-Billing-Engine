from enum import Enum


class UsageType(str, Enum):
    API_CALLS = "api_calls"
    AI_TOKENS = "ai_tokens"
