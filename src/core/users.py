"""User manager and dependency injection module.

Handles business logic for user lifecycle management, password verification,
and FastAPI dependency injection adapters for user database operations.
"""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.session import get_db_session
from src.models.user import User


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Manager providing core business logic for user account management.

    Handles account registration, password reset token generation, and authentication lifecycle.
    """

    def __init__(self, user_db: SQLAlchemyUserDatabase[User, uuid.UUID]) -> None:
        """Initializes UserManager instance with dynamic configuration settings."""
        super().__init__(user_db)
        self.reset_password_token_secret = settings.RESET_PASSWORD_TOKEN_SECRET
        self.verification_token_secret = settings.VERIFICATION_TOKEN_SECRET


async def get_user_db(
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID], None]:
    """Dependency generator providing SQLAlchemy user database adapter.

    Args:
        session: Active async database session.

    Yields:
        SQLAlchemyUserDatabase instance bound to current session.
    """
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),  # noqa: B008
) -> AsyncGenerator[UserManager, None]:
    """Dependency generator providing UserManager instance.

    Args:
        user_db: User database adapter instance.

    Yields:
        UserManager instance initialized with user database adapter.
    """
    yield UserManager(user_db)
