"""User manager and dependency injection module.

Handles business logic for user lifecycle management, password verification,
and FastAPI dependency injection adapters for user database operations.
"""

import hashlib
import logging
import uuid
from collections.abc import AsyncGenerator

import httpx
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
from fastapi_users.exceptions import InvalidPasswordException
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession
from zxcvbn import zxcvbn

from src.core.auth import auth_backend
from src.core.config import settings
from src.core.mail import send_transactional_email
from src.db.session import get_db_session
from src.models.user import User

logger = logging.getLogger(__name__)


async def is_password_pwned(password: str) -> bool:
    """Checks whether a password has appeared in a known data breach using HIBP API.

    Uses k-Anonymity by hashing the password with SHA-1 and querying api.pwnedpasswords.com
    with the first 5 characters of the hash.

    Args:
        password: Raw plaintext password to evaluate.

    Returns:
        True if the password hash suffix is present in the HIBP response, False otherwise.
    """
    sha1_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1_hash[:5], sha1_hash[5:]

    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            response = await client.get(f"https://api.pwnedpasswords.com/range/{prefix}")
            if response.status_code == 200:
                hashes = (line.split(":") for line in response.text.splitlines())
                for h, _count in hashes:
                    if h == suffix:
                        return True
            else:
                # Non-200 responses (e.g. rate limiting 429, service unavailable 503) log a warning
                # and fall through to return False (fail-open strategy so third-party degradation
                # does not block user registration).
                logger.warning(f"HIBP API returned non-200 status code {response.status_code} for prefix {prefix}")
        except httpx.RequestError as exc:
            # Fail-open gracefully if HIBP API is unreachable or times out
            logger.warning(f"HIBP API request failed for prefix {prefix}: {exc}")
            return False
    return False


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Manager providing core business logic for user account management.

    Handles account registration, password reset token generation, and authentication lifecycle.
    """

    def __init__(self, user_db: SQLAlchemyUserDatabase[User, uuid.UUID]) -> None:
        """Initializes UserManager instance with dynamic configuration settings."""
        super().__init__(user_db)
        self.reset_password_token_secret = settings.RESET_PASSWORD_TOKEN_SECRET
        self.verification_token_secret = settings.VERIFICATION_TOKEN_SECRET

    async def validate_password(
        self,
        password: str,
        user: schemas.BaseUserCreate | User | None = None,
    ) -> None:
        """Validates password against complexity, entropy, and data breach standards.

        Args:
            password: Raw password candidate string.
            user: Associated UserCreate request schema or User entity instance if available.

        Returns:
            None if the password satisfies all length, entropy, and breach criteria.

        Raises:
            InvalidPasswordException: If password violates length, entropy score, or HIBP checks.
        """
        min_length = 12
        max_length = 128

        if len(password) < min_length:
            raise InvalidPasswordException(reason=f"Password must be at least {min_length} characters long.")

        if len(password) > max_length:
            raise InvalidPasswordException(reason=f"Password cannot exceed {max_length} characters long.")

        # Build user-specific context for zxcvbn dictionary matching
        user_inputs: list[str] = []
        if user is not None:
            email = getattr(user, "email", None)
            if isinstance(email, str) and email:
                user_inputs.append(email.split("@")[0])
            first_name = getattr(user, "first_name", None)
            if isinstance(first_name, str) and first_name:
                user_inputs.append(first_name)
            last_name = getattr(user, "last_name", None)
            if isinstance(last_name, str) and last_name:
                user_inputs.append(last_name)

        # NOTE: zxcvbn returns a dict that contains the raw password under the 'password'
        # key. Explicitly delete the result after evaluation to minimise the window in
        # which the plaintext is reachable via a live object reference.
        zxcvbn_result = None
        try:
            zxcvbn_result = zxcvbn(password, user_inputs=user_inputs)
            score: int = zxcvbn_result.get("score", 0)
            if score < 3:
                feedback_dict = zxcvbn_result.get("feedback", {})
                suggestions = feedback_dict.get("suggestions", [])
                warning = feedback_dict.get("warning", "")
                feedback_msg = " ".join(suggestions) or warning or "Password is too weak or easy to guess."
                raise InvalidPasswordException(reason=f"Weak password: {feedback_msg}")
        except InvalidPasswordException:
            raise
        except Exception as exc:
            # Catch unexpected errors from zxcvbn without propagating a traceback that
            # contains `password` in its frame locals.
            raise InvalidPasswordException(reason="Password validation failed unexpectedly.") from exc
        finally:
            # Ensure the zxcvbn result dict (which holds the raw password) is released
            # as soon as possible, regardless of the evaluation outcome.
            if zxcvbn_result is not None:
                del zxcvbn_result

        if await is_password_pwned(password):
            raise InvalidPasswordException(
                reason="This password has appeared in a known data breach. Please choose a different password."
            )

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
