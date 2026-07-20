from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DEFAULT_JWT_SECRET = "dev_secret_jwt_key_must_be_changed_in_production_32chars"
_DEV_DEFAULT_DATABASE_URL = "postgresql+asyncpg://savings_user:savings_dev_password@localhost:5432/savings_dev"


class Settings(BaseSettings):
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

    # Settings configuration
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Self:
        if self.ENVIRONMENT == "production":
            if self.JWT_SECRET == _DEV_DEFAULT_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET must be explicitly set to a custom secure value in production environments."
                )
            if self.DATABASE_URL == _DEV_DEFAULT_DATABASE_URL:
                raise ValueError(
                    "DATABASE_URL must be explicitly set to a custom database URL in production environments."
                )
            if not self.DATABASE_SSL:
                raise ValueError("DATABASE_SSL must be True in production environments.")
        return self


settings = Settings()
