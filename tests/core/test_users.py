"""Unit tests for user manager business logic and initialization."""

from unittest.mock import MagicMock

from src.core.users import UserManager


def test_user_manager_initialization() -> None:
    """Verify that UserManager initializes correctly with user database adapter and security tokens."""
    user_db_mock = MagicMock()
    manager = UserManager(user_db_mock)
    assert manager.user_db == user_db_mock
    assert manager.reset_password_token_secret is not None
    assert manager.verification_token_secret is not None
