"""Unit tests for user Pydantic schemas validation and serialization."""

import pytest
from pydantic import ValidationError

from src.core.constants import TaxBand
from src.schemas.user import UserCreate, UserUpdate


def test_user_create_schema_valid() -> None:
    """Verify that UserCreate accepts valid attributes and populates schema fields correctly."""
    user_data = UserCreate(
        email="test@example.com",
        password="secure_password123",
        first_name="Alice",
        last_name="Smith",
        tax_band=TaxBand.HIGHER.value,
    )
    assert user_data.email == "test@example.com"
    assert user_data.first_name == "Alice"
    assert user_data.last_name == "Smith"
    assert user_data.tax_band == TaxBand.HIGHER.value


def test_user_create_schema_invalid_tax_band() -> None:
    """Verify that UserCreate raises ValidationError when an invalid tax band string is provided."""
    with pytest.raises(ValidationError):
        UserCreate(
            email="test@example.com",
            password="secure_password123",
            first_name="Alice",
            last_name="Smith",
            tax_band="invalid_band",  # type: ignore[arg-type]
        )


def test_user_update_schema() -> None:
    """Verify that UserUpdate supports partial attribute updates and validates tax band values."""
    update_data = UserUpdate(first_name="Bob", tax_band=TaxBand.ADDITIONAL.value)
    assert update_data.first_name == "Bob"
    assert update_data.last_name is None
    assert update_data.tax_band == TaxBand.ADDITIONAL.value
