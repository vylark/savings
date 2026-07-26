"""User manager and dependency injection module.

Handles business logic for user lifecycle management, password verification,
and FastAPI dependency injection adapters for user database operations.
"""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import auth_backend
from src.core.config import settings
from src.core.mail import send_transactional_email
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

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Lifecycle hook invoked following successful user registration.

        Args:
            user: Registered User entity instance.
            request: Optional active FastAPI Request object.
        """
        await send_transactional_email(
            subject="Welcome to Savings Platform",
            recipient_email=user.email,
            body_text=f"Welcome {user.first_name}!",
        )
        await self.request_verify(user, request)

    async def on_after_request_verify(self, user: User, token: str, request: Request | None = None) -> None:
        """Lifecycle hook invoked when a user requests an account verification token.

        Args:
            user: Requesting User entity instance.
            token: Generated account verification token string.
            request: Optional active FastAPI Request object.
        """
        await send_transactional_email(
            subject="Account Verification Token",
            recipient_email=user.email,
            body_text=f"Hello {user.first_name}, your email verification token is: {token}",
        )

    async def on_after_forgot_password(self, user: User, token: str, request: Request | None = None) -> None:
        """Lifecycle hook invoked when a user requests a password reset token.

        Args:
            user: Requesting User entity instance.
            token: Generated password reset token string.
            request: Optional active FastAPI Request object.
        """
        await send_transactional_email(
            subject="Password Reset Request",
            recipient_email=user.email,
            body_text=f"Hello {user.first_name}, your password reset token is: {token}",
        )


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


fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)

current_active_user = fastapi_users.current_user(active=True)
current_verified_user = fastapi_users.current_user(active=True, verified=True)
