"""User API validation and serialization schemas.

Defines Pydantic request and response schemas for user account creation, reading, and updates.
"""

import uuid

from fastapi_users import schemas
from pydantic import Field

from src.core.constants import TaxBandType


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Schema for serializing user account response payloads.

    Attributes:
        first_name: Given name of the user.
        last_name: Surname of the user.
        tax_band: UK income tax band classification.
    """

    first_name: str
    last_name: str
    tax_band: TaxBandType


class UserCreate(schemas.BaseUserCreate):
    """Schema for validating user registration request payloads.

    Attributes:
        first_name: Given name (1-100 characters).
        last_name: Surname (1-100 characters).
        tax_band: UK income tax band classification (defaults to 'basic').
    """

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    tax_band: TaxBandType = "basic"


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for validating user profile update request payloads.

    Attributes:
        first_name: Optional updated given name (1-100 characters).
        last_name: Optional updated surname (1-100 characters).
        tax_band: Optional updated UK income tax band classification.
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    tax_band: TaxBandType | None = None
