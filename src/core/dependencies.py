"""Core FastAPI dependency functions and security guard adapters.

Provides reusable dependencies for resolving authenticated users and enforcing
mandatory Multi-Factor Authentication (TOTP 2FA) checks on sensitive endpoints.
"""

from fastapi import Depends, Header, HTTPException, status

from src.core.security import decrypt_secret, verify_totp_code
from src.core.users import current_active_user
from src.models.user import User


async def get_current_user_from_req(
    user: User = Depends(current_active_user),  # noqa: B008
) -> User:
    """Dependency wrapper resolving current authenticated active user.

    Args:
        user: Active User entity resolved from JWT session token.

    Returns:
        User entity instance.
    """
    return user


async def require_totp(
    user: User = Depends(get_current_user_from_req),  # noqa: B008
    x_totp_code: str | None = Header(default=None, alias="X-TOTP-Code"),
) -> User:
    """Reusable FastAPI dependency enforcing mandatory 2FA on high-risk operations.

    Evaluates mandatory 2FA policy:
    1. If user does not have 2FA enabled, raises HTTP 428 Precondition Required.
    2. If X-TOTP-Code header is missing or invalid, raises HTTP 401 Unauthorized.

    Args:
        user: Authenticated active user entity.
        x_totp_code: 6-digit TOTP code passed in HTTP request header.

    Raises:
        HTTPException: HTTP 428 if 2FA is not enabled; HTTP 401 if TOTP code is missing/invalid.

    Returns:
        Authenticated User instance upon successful 2FA verification.
    """
    if not user.is_totp_enabled or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="2FA_SETUP_REQUIRED: Two-factor authentication setup is mandatory for high-risk operations.",
        )

    if not x_totp_code:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-TOTP-Code header for protected operation.",
        )

    plain_secret = decrypt_secret(user.totp_secret)
    if not verify_totp_code(plain_secret, x_totp_code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 6-digit TOTP passcode provided in X-TOTP-Code header.",
        )

    return user
