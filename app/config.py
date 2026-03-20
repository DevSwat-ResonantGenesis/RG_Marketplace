"""Marketplace Service configuration."""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"postgresql+asyncpg://{os.getenv('MARKETPLACE_DB_USER', os.getenv('AUTH_DB_USER', 'doadmin'))}:"
        f"{os.getenv('MARKETPLACE_DB_PASSWORD', os.getenv('AUTH_DB_PASSWORD', ''))}@"
        f"{os.getenv('MARKETPLACE_DB_HOST', os.getenv('AUTH_DB_HOST', 'db'))}:"
        f"{os.getenv('MARKETPLACE_DB_PORT', os.getenv('AUTH_DB_PORT', '5432'))}/"
        f"{os.getenv('MARKETPLACE_DB_NAME', os.getenv('AUTH_DB_NAME', 'defaultdb'))}?sslmode=require"
    )

    # Service URLs
    USER_SERVICE_URL: str = "http://user_service:8000"
    ED_SERVICE_URL: str = "http://ed_service:8000"
    STORAGE_SERVICE_URL: str = "http://storage_service:8000"
    WORKFLOW_SERVICE_URL: str = "http://workflow_service:8000"

    # Stripe configuration
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""

    # Marketplace settings
    PLATFORM_FEE_PERCENT: float = 15.0  # 15% platform fee
    MIN_AGENT_PRICE: float = 0.0  # Free agents allowed
    MAX_AGENT_PRICE: float = 10000.0
    REVIEW_MIN_LENGTH: int = 10
    REVIEW_MAX_LENGTH: int = 2000

    class Config:
        env_prefix = "MARKETPLACE_"
        case_sensitive = False


settings = Settings()
