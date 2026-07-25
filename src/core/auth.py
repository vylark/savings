"""Authentication backend and token strategy configuration module.

Defines transport mechanisms, token signing strategies, and the unified FastAPI-Users authentication backend.
"""

import uuid

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from src.core.config import settings
from src.models.user import User

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy[User, uuid.UUID]:
    """Instantiates a stateless JWT strategy for user authentication.

    Returns:
        JWTStrategy configured with secret key and 30-minute token lifespan.
    """
    return JWTStrategy(
        secret=settings.JWT_SECRET,
        lifetime_seconds=1800,
    )


auth_backend: AuthenticationBackend[User, uuid.UUID] = AuthenticationBackend[User, uuid.UUID](
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
