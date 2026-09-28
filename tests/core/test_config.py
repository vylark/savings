"""Unit tests for Pydantic application settings and environment validation."""

import pytest

from src.core.config import Settings


def test_default_settings_load() -> None:
    """Verify loading default development settings and minimum secret length constraints."""
    settings = Settings()
    assert settings.ENVIRONMENT == "development"
    assert len(settings.RESET_PASSWORD_TOKEN_SECRET) >= 32
    assert len(settings.VERIFICATION_TOKEN_SECRET) >= 32


def test_production_validation_rejects_default_secrets() -> None:
    """Verify that production validation rejects default development secrets for reset/verification tokens."""
    with pytest.raises(ValueError, match="RESET_PASSWORD_TOKEN_SECRET must be explicitly set"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET="custom_secure_jwt_secret_value_32chars",
            RESET_PASSWORD_TOKEN_SECRET="dev_reset_password_secret_key_must_be_changed_32chars",
            VERIFICATION_TOKEN_SECRET="custom_secure_verification_secret_32chars",
            DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db",
            DATABASE_SSL=True,
        )

    with pytest.raises(ValueError, match="VERIFICATION_TOKEN_SECRET must be explicitly set"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET="custom_secure_jwt_secret_value_32chars",
            RESET_PASSWORD_TOKEN_SECRET="custom_secure_reset_password_secret_32chars",
            VERIFICATION_TOKEN_SECRET="dev_verification_secret_key_must_be_changed_in_32chars",
            DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db",
            DATABASE_SSL=True,
        )
