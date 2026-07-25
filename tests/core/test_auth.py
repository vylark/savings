"""Unit tests for FastAPI Users authentication backend configuration and JWT strategy."""

from src.core.auth import auth_backend, bearer_transport, get_jwt_strategy


def test_auth_backend_configuration() -> None:
    """Verify that authentication backend is configured with JWT scheme and correct bearer transport."""
    assert auth_backend.name == "jwt"
    assert auth_backend.transport == bearer_transport
    assert bearer_transport.scheme.model.flows.password.tokenUrl == "auth/jwt/login"  # type: ignore[attr-defined]


def test_jwt_strategy_creation() -> None:
    """Verify that get_jwt_strategy creates a JWT strategy with the configured lifetime."""
    strategy = get_jwt_strategy()
    assert strategy.lifetime_seconds == 1800
