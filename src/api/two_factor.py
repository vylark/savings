"""Multi-Factor Authentication (TOTP 2FA) API routes and mandatory dependency module.

Provides endpoints for TOTP key setup, 2FA activation, code verification, and a reusable
FastAPI dependency enforcing mandatory 2FA on high-risk operations.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import (
    decrypt_secret,
    encrypt_secret,
    generate_qr_code_base64,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
)
from src.core.users import current_active_user
from src.db.session import get_db_session
from src.models.user import User


class TOTPSetupResponse(BaseModel):
    """Response payload for 2FA setup request containing provisioning details.

    Attributes:
        secret: Plaintext base32 TOTP secret string.
        provisioning_uri: Standard OTPAuth provisioning URI string.
        qr_code: Base64 encoded PNG image data URI for QR code scanning.
    """

    secret: str
    provisioning_uri: str
    qr_code: str


class TOTPCodeRequest(BaseModel):
    """Request payload containing 6-digit TOTP passcode.

    Attributes:
        code: 6-digit numerical OTP string.
    """

    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TOTPMessageResponse(BaseModel):
    """Standard message response for 2FA operations.

    Attributes:
        status: Operation status indicator.
        message: Descriptive human-readable result message.
    """

    status: str
    message: str


router = APIRouter(prefix="/auth/2fa", tags=["Auth 2FA"])


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


@router.post("/setup", response_model=TOTPSetupResponse)
async def setup_totp(
    user: User = Depends(get_current_user_from_req),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TOTPSetupResponse:
    """Generates a new TOTP secret key, saves encrypted secret in database, and returns QR code payload.

    Args:
        user: Active authenticated User entity.
        session: Database session dependency.

    Returns:
        TOTPSetupResponse containing secret, provisioning URI, and base64 QR code image.
    """
    plain_secret = generate_totp_secret()
    encrypted_secret = encrypt_secret(plain_secret)

    user.totp_secret = encrypted_secret
    session.add(user)
    await session.commit()
    await session.refresh(user)

    provisioning_uri = get_totp_uri(plain_secret, user.email)
    qr_code_b64 = generate_qr_code_base64(provisioning_uri)

    return TOTPSetupResponse(
        secret=plain_secret,
        provisioning_uri=provisioning_uri,
        qr_code=qr_code_b64,
    )


@router.post("/enable", response_model=TOTPMessageResponse)
async def enable_totp(
    payload: TOTPCodeRequest,
    user: User = Depends(get_current_user_from_req),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> TOTPMessageResponse:
    """Verifies initial TOTP code and activates 2FA (is_totp_enabled=True) for user account.

    Args:
        payload: TOTPCodeRequest payload containing 6-digit OTP code.
        user: Active authenticated User entity.
        session: Database session dependency.

    Raises:
        HTTPException: HTTP 400 if setup has not been initiated or code is invalid.

    Returns:
        TOTPMessageResponse indicating successful 2FA activation.
    """
    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP 2FA setup must be initiated via /auth/2fa/setup before enabling.",
        )

    plain_secret = decrypt_secret(user.totp_secret)
    if not verify_totp_code(plain_secret, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid 6-digit TOTP passcode.",
        )

    user.is_totp_enabled = True
    session.add(user)
    await session.commit()

    return TOTPMessageResponse(
        status="success",
        message="Multi-factor authentication (2FA) successfully enabled.",
    )


@router.post("/verify", response_model=TOTPMessageResponse)
async def verify_totp(
    payload: TOTPCodeRequest,
    user: User = Depends(get_current_user_from_req),  # noqa: B008
) -> TOTPMessageResponse:
    """Verifies a 6-digit TOTP passcode for active 2FA enabled account.

    Args:
        payload: TOTPCodeRequest payload containing 6-digit OTP code.
        user: Active authenticated User entity.

    Raises:
        HTTPException: HTTP 400 if 2FA is not enabled or code is invalid.

    Returns:
        TOTPMessageResponse indicating successful verification.
    """
    if not user.is_totp_enabled or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled for this user account.",
        )

    plain_secret = decrypt_secret(user.totp_secret)
    if not verify_totp_code(plain_secret, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid 6-digit TOTP passcode.",
        )

    return TOTPMessageResponse(
        status="success",
        message="TOTP code successfully verified.",
    )


@router.post("/protected-action", response_model=TOTPMessageResponse)
async def protected_high_risk_action(
    user: User = Depends(require_totp),  # noqa: B008
) -> TOTPMessageResponse:
    """Sample protected endpoint demonstrating high-risk action guarded by require_totp dependency.

    Args:
        user: Verified user entity backed by mandatory TOTP check.

    Returns:
        TOTPMessageResponse confirming execution of high-risk operation.
    """
    return TOTPMessageResponse(
        status="success",
        message=f"High-risk action executed successfully for verified user {user.email}.",
    )
