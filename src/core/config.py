from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    
    # Database Configurations
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://savings_user:savings_dev_password@localhost:5432/savings_dev"
    )
    DATABASE_SSL: bool = Field(default=False)
    
    # Authentication Security
    JWT_SECRET: str = Field(default="temporary_dev_secret_key_change_me")
    
    # Configurations configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
