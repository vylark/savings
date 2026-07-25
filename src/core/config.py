"""Application configuration and settings management module.

Parses environment variables via Pydantic Settings and enforces security validation for production environments.
"""

from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DEFAULT_JWT_SECRET = "dev_secret_jwt_key_must_be_changed_in_production_32chars"
_DEV_DEFAULT_RESET_PASSWORD_SECRET = "dev_reset_password_secret_key_must_be_changed_32chars"
_DEV_DEFAULT_VERIFICATION_SECRET = "dev_verification_secret_key_must_be_changed_in_32chars"
_DEV_DEFAULT_DATABASE_URL = "postgresql+asyncpg://savings_user:savings_dev_password@localhost:5432/savings_dev"


class Settings(BaseSettings):
    """Application settings class validating configuration parameters.

    Attributes:
        ENVIRONMENT: Current deployment environment ('development', 'production', or 'test').
        DATABASE_URL: Connection URL for PostgreSQL database.
        DATABASE_SSL: Enables SSL mode for database connections.
        DATABASE_CA_FILE: Path to custom CA certificate file for SSL verification.
        JWT_SECRET: Secret key used to sign and verify session JWT access tokens.
        RESET_PASSWORD_TOKEN_SECRET: Secret key used to sign password reset tokens.
        VERIFICATION_TOKEN_SECRET: Secret key used to sign account verification tokens.
    """

    ENVIRONMENT: Literal["development", "production", "test"] = "development"

    # Database Configurations
    DATABASE_URL: str = Field(default=_DEV_DEFAULT_DATABASE_URL)
    DATABASE_SSL: bool = Field(default=False)
    DATABASE_CA_FILE: str | None = Field(default=None)

    # Authentication Security
    JWT_SECRET: str = Field(
        default=_DEV_DEFAULT_JWT_SECRET,
        min_length=32,
    )
    JWT_LIFETIME_SECONDS: int = Field(
        default=1800,
        ge=60,
    )
    RESET_PASSWORD_TOKEN_SECRET: str = Field(
        default=_DEV_DEFAULT_RESET_PASSWORD_SECRET,
        min_length=32,
    )
    VERIFICATION_TOKEN_SECRET: str = Field(
        default=_DEV_DEFAULT_VERIFICATION_SECRET,
        min_length=32,
    )

    # Settings configuration
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Self:
        """Validates that production environment variables use hardened values.

        Raises:
            ValueError: If default development secrets or unencrypted DB settings are detected in production.

        Returns:
            Validated Settings instance.
        """
        if self.ENVIRONMENT == "production":
            if self.JWT_SECRET == _DEV_DEFAULT_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET must be explicitly set to a custom secure value in production environments."
                )
            if self.RESET_PASSWORD_TOKEN_SECRET == _DEV_DEFAULT_RESET_PASSWORD_SECRET:
                raise ValueError(
                    "RESET_PASSWORD_TOKEN_SECRET must be explicitly set to a custom secure value in production environments."
                )
            if self.VERIFICATION_TOKEN_SECRET == _DEV_DEFAULT_VERIFICATION_SECRET:
                raise ValueError(
                    "VERIFICATION_TOKEN_SECRET must be explicitly set to a custom secure value in production environments."
                )
            if self.DATABASE_URL == _DEV_DEFAULT_DATABASE_URL:
                raise ValueError(
                    "DATABASE_URL must be explicitly set to a custom database URL in production environments."
                )
            if not self.DATABASE_SSL:
                raise ValueError("DATABASE_SSL must be True in production environments.")
        return self


settings = Settings()
