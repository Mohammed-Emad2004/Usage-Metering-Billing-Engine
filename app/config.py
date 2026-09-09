from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/flyrank_metering"
    STRIPE_SECRET_KEY: str = "sk_test_placeholder"
    STRIPE_WEBHOOK_SECRET: str = "whsec_placeholder"
    STRIPE_PRO_PRICE_ID: str = "price_test_placeholder"
    ENVIRONMENT: str = "development"

    # ── Pricing constants (integer cents) ──────────────────────────
    # All prices are in integer cents. Token prices are per 1,000 tokens.
    # Reasoning tokens use the same rate as output tokens (capstone rule).
    API_CALL_PRICE_CENTS: int = 1
    INPUT_TOKEN_PRICE_CENTS_PER_1K: int = 3
    CACHED_INPUT_TOKEN_PRICE_CENTS_PER_1K: int = 1
    OUTPUT_TOKEN_PRICE_CENTS_PER_1K: int = 15
    REASONING_TOKEN_PRICE_CENTS_PER_1K: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
