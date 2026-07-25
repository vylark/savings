"""Savings and Investments API entrypoint module.

Initializes the FastAPI application, mounts authentication and user profile routers,
and defines application health check endpoints.
"""

import uuid

from fastapi import FastAPI
from fastapi_users import FastAPIUsers

from src.core.auth import auth_backend
from src.core.users import get_user_manager
from src.models.user import User
from src.schemas.user import UserCreate, UserRead, UserUpdate

fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)

app = FastAPI(
    title="Savings and Investments API",
    description="Backend unified single-entry ledger platform tracking fractional physical/virtual savings.",
    version="0.1.0",
)

# 1. Register Auth Router (handles login / logout)
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["Auth"],
)

# 2. Register Registration Router (handles account creation)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["Auth"],
)

# 3. Register Users Router (handles /users/me for reading & editing profile info)
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
