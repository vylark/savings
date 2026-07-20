from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: Literal["development", "production", "test"] = "development"

    # Database Configurations
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://savings_user:savings_dev_password@localhost:5432/savings_dev"
    )
    DATABASE_SSL: bool = Field(default=False)
    DATABASE_CA_FILE: str | None = Field(default=None)

    # Authentication Security
    JWT_SECRET: str = Field(..., min_length=32)

    # Settings configuration
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
