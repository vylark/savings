"""Unit tests for user manager business logic and initialization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi_users.exceptions import InvalidPasswordException

from src.core.users import HIBPServiceException, UserManager
from src.schemas.user import UserCreate


def test_user_manager_initialization() -> None:
    """Verify that UserManager initializes correctly with user database adapter and security tokens."""
    user_db_mock = MagicMock()
    manager = UserManager(user_db_mock)
    assert manager.user_db == user_db_mock
    assert manager.reset_password_token_secret is not None
    assert manager.verification_token_secret is not None


@pytest.mark.asyncio
async def test_validate_password_too_short() -> None:
    """Verify that validate_password raises InvalidPasswordException for passwords < 12 characters."""
    manager = UserManager(MagicMock())
    with pytest.raises(InvalidPasswordException) as exc_info:
        await manager.validate_password("Short1!")
    assert "at least 12 characters" in exc_info.value.reason


@pytest.mark.asyncio
async def test_validate_password_too_long() -> None:
    """Verify that validate_password raises InvalidPasswordException for passwords > 128 characters."""
    manager = UserManager(MagicMock())
    long_password = "A" * 129
    with pytest.raises(InvalidPasswordException) as exc_info:
        await manager.validate_password(long_password)
    assert "cannot exceed 128 characters long." in exc_info.value.reason


@pytest.mark.asyncio
async def test_validate_password_weak_entropy() -> None:
    """Verify that validate_password raises InvalidPasswordException for weak or dictionary passwords."""
    manager = UserManager(MagicMock())
    with patch("src.core.users.is_password_pwned", new=AsyncMock(return_value=False)):
        with pytest.raises(InvalidPasswordException) as exc_info:
            await manager.validate_password("password123456")
        assert "Weak password" in exc_info.value.reason


@pytest.mark.asyncio
async def test_validate_password_pwned() -> None:
    """Verify that validate_password raises InvalidPasswordException when password appears in breach database."""
    manager = UserManager(MagicMock())
    with patch("src.core.users.is_password_pwned", new=AsyncMock(return_value=True)):
        with pytest.raises(InvalidPasswordException) as exc_info:
            await manager.validate_password("SavingsPlatform2026!XyZ#9")
        assert "appeared in a known data breach" in exc_info.value.reason


@pytest.mark.asyncio
async def test_validate_password_valid_success() -> None:
    """Verify that a strong, unpwned password passes validation without error."""
    manager = UserManager(MagicMock())
    user_schema = UserCreate(
        email="test@example.com",
        password="SavingsPlatform2026!XyZ#9",
        first_name="Jane",
        last_name="Doe",
    )
    with patch("src.core.users.is_password_pwned", new=AsyncMock(return_value=False)):
        await manager.validate_password("SavingsPlatform2026!XyZ#9", user=user_schema)


@pytest.mark.asyncio
async def test_validate_password_hibp_service_fail_open_success() -> None:
    """Verify that password validation passes when HIBP is offline and fail-open is enabled."""
    manager = UserManager(MagicMock())
    with patch("src.core.users.is_password_pwned", side_effect=HIBPServiceException("Offline")):
        with patch("src.core.users.settings.HIBP_FAIL_OPEN", True):
            # Should not raise exception
            await manager.validate_password("SavingsPlatform2026!XyZ#9")


@pytest.mark.asyncio
async def test_validate_password_hibp_service_fail_closed_error() -> None:
    """Verify that password validation fails when HIBP is offline and fail-open is disabled."""
    manager = UserManager(MagicMock())
    with patch("src.core.users.is_password_pwned", side_effect=HIBPServiceException("Offline")):
        with patch("src.core.users.settings.HIBP_FAIL_OPEN", False):
            with pytest.raises(InvalidPasswordException) as exc_info:
                await manager.validate_password("SavingsPlatform2026!XyZ#9")
            assert "verification service is currently unavailable" in exc_info.value.reason


@pytest.mark.asyncio
async def test_validate_password_user_context_rejection() -> None:
    """Verify zxcvbn entropy check utilizes user context fields to reject custom weak passwords."""
    manager = UserManager(MagicMock())
    user_schema = UserCreate(
        email="john.smith@example.com",
        password="SavingsPlatform2026!XyZ#9",
        first_name="John",
        last_name="Smith",
    )
    with patch("src.core.users.is_password_pwned", new=AsyncMock(return_value=False)):
        with pytest.raises(InvalidPasswordException) as exc_info:
            # Password contains repeated first name which drops entropy
            await manager.validate_password("JohnJohnJohn!", user=user_schema)
        assert "Weak password" in exc_info.value.reason
