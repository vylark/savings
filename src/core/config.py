"""Application configuration and settings management module.

Parses environment variables via Pydantic Settings and enforces security validation for production environments.
"""

from typing import Literal, Self

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DEFAULT_JWT_SECRET = "dev_secret_jwt_key_must_be_changed_in_production_32chars"
_DEV_DEFAULT_RESET_PASSWORD_SECRET = "dev_reset_password_secret_key_must_be_changed_32chars"
_DEV_DEFAULT_VERIFICATION_SECRET = "dev_verification_secret_key_must_be_changed_in_32chars"
_DEV_DEFAULT_DATABASE_URL = "postgresql+asyncpg://savings_user:savings_dev_password@localhost:5432/savings_dev"
_DEV_DEFAULT_TOTP_SECRET_KEY = "ZGV2X3RvdHBfc2VjcmV0X2tleV8zMmJ5dGVzXzEyMzQ="


class Settings(BaseSettings):
    """Application settings class validating configuration parameters.

    Attributes:
        ENVIRONMENT: Current deployment environment ('development', 'production', or 'test').
        DATABASE_URL: Connection URL for PostgreSQL database.
        DATABASE_SSL: Enables SSL mode for database connections.
        DATABASE_CA_FILE: Path to custom CA certificate file for SSL verification.
        JWT_SECRET: Secret key used to sign and verify session JWT access tokens.
        JWT_LIFETIME_SECONDS: Token lifetime in seconds for issued JWT access tokens.
        RESET_PASSWORD_TOKEN_SECRET: Secret key used to sign password reset tokens.
        VERIFICATION_TOKEN_SECRET: Secret key used to sign account verification tokens.
        REDIS_URL: Connection URL for Redis rate limiting storage backend.
        TOTP_SECRET_KEY: Fernet key used to encrypt user TOTP secrets at rest.
        SMTP_HOST: SMTP server hostname for transactional email.
        SMTP_PORT: SMTP server port number.
        SMTP_USER: SMTP authentication username.
        SMTP_PASSWORD: SMTP authentication password.
        EMAILS_FROM_EMAIL: Sender email address for outbound system emails.
        EMAILS_FROM_NAME: Display name of sender for outbound system emails.
        SUPPRESS_SEND: Disables network email transport when True (for local dev/tests).
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
    TOTP_SECRET_KEY: str = Field(
        default=_DEV_DEFAULT_TOTP_SECRET_KEY,
        min_length=32,
    )

    # Password Policy & HIBP Validation
    PASSWORD_MIN_LENGTH: int = Field(default=12, ge=8)
    PASSWORD_MAX_LENGTH: int = Field(default=128, le=256)
    HIBP_FAIL_OPEN: bool = Field(default=True)
    HIBP_TIMEOUT: float = Field(default=3.0, ge=0.1)

    # Redis & Rate Limiting
    REDIS_URL: str | None = Field(default=None)

    # Transactional Email Transport
    SMTP_HOST: str | None = Field(default=None)
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str | None = Field(default=None)
    SMTP_PASSWORD: str | None = Field(default=None)
    EMAILS_FROM_EMAIL: str = Field(default="noreply@savings.local")
    EMAILS_FROM_NAME: str = Field(default="Savings Platform")
    SUPPRESS_SEND: bool = Field(default=True)

    # Settings configuration
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_security_keys(self) -> Self:
        """Validates security keys and production environment requirements.

        Raises:
            ValueError: If TOTP_SECRET_KEY is not a valid Fernet key or if default development secrets
                        and unencrypted DB settings are detected in production.

        Returns:
            Validated Settings instance.
        """
        try:
            Fernet(self.TOTP_SECRET_KEY.encode("utf-8"))
        except Exception as err:
            raise ValueError("TOTP_SECRET_KEY must be a 32 url-safe base64-encoded bytes Fernet key.") from err

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
            if self.TOTP_SECRET_KEY == _DEV_DEFAULT_TOTP_SECRET_KEY:
                raise ValueError(
                    "TOTP_SECRET_KEY must be explicitly set to a custom secure value in production environments."
                )
            if self.DATABASE_URL == _DEV_DEFAULT_DATABASE_URL:
                raise ValueError(
                    "DATABASE_URL must be explicitly set to a custom database URL in production environments."
                )
            if not self.DATABASE_SSL:
                raise ValueError("DATABASE_SSL must be True in production environments.")
        return self


settings = Settings()
