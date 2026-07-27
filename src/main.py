"""Savings and Investments API entrypoint module.

Initializes the FastAPI application, mounts authentication, user profile, email verification,
and 2FA routers, and attaches slowapi rate limiting middleware.
"""

from fastapi import Depends, FastAPI, Request
from fastapi.routing import APIRoute
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.api.two_factor import router as two_factor_router
from src.core.auth import auth_backend
from src.core.limiter import limiter
from src.core.users import current_verified_user, fastapi_users
from src.models.user import User
from src.schemas.user import UserCreate, UserRead, UserUpdate

app = FastAPI(
    title="Savings and Investments API",
    description="Backend unified single-entry ledger platform tracking fractional physical/virtual savings.",
    version="0.1.0",
)

# Rate Limiting state and middleware configuration
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]

app.add_middleware(SlowAPIMiddleware)

# 1. Register Auth Router (handles login / logout) with 5 req/min rate limit on login
auth_router = fastapi_users.get_auth_router(auth_backend)
for route in auth_router.routes:
    if isinstance(route, APIRoute) and route.path == "/login":
        route.endpoint = limiter.limit("5/minute")(route.endpoint)

app.include_router(
    auth_router,
    prefix="/auth/jwt",
    tags=["Auth"],
)

# 2. Register Registration Router (handles account creation) with 3 req/hr rate limit
register_router = fastapi_users.get_register_router(UserRead, UserCreate)
for route in register_router.routes:
    if isinstance(route, APIRoute) and route.path == "/register":
        route.endpoint = limiter.limit("3/hour")(route.endpoint)

app.include_router(
    register_router,
    prefix="/auth",
    tags=["Auth"],
)

# 3. Register Verification Router (handles request-verify-token and verify)
verify_router = fastapi_users.get_verify_router(UserRead)
app.include_router(
    verify_router,
    prefix="/auth",
    tags=["Auth"],
)

# 4. Register Reset Password Router (handles forgot-password and reset-password)
reset_password_router = fastapi_users.get_reset_password_router()
app.include_router(
    reset_password_router,
    prefix="/auth",
    tags=["Auth"],
)

# 5. Register Multi-Factor Authentication Router (handles 2FA setup, enable, verify, and mandatory protected action)
app.include_router(
    two_factor_router,
)

# 6. Register Users Router (handles /users/me for reading & editing profile info)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["Users"],
)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint to verify container and server operation.

    Returns:
        Dictionary containing status indicator ('healthy').
    """
    return {"status": "healthy"}


@app.get("/protected/verified-only", tags=["Protected"])
@limiter.limit("30/minute")
async def verified_only_route(
    request: Request,
    user: User = Depends(current_verified_user),  # noqa: B008
) -> dict[str, str]:
    """Sample protected endpoint requiring active and verified account.

    Args:
        request: FastAPI Request object for slowapi rate limiting.
        user: Active and verified user entity.

    Returns:
        Dictionary with confirmation message.
    """
    return {"message": f"Access granted to verified user {user.email}"}
