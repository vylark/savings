from src.core.auth import auth_backend, bearer_transport, get_jwt_strategy


def test_auth_backend_configuration() -> None:
    assert auth_backend.name == "jwt"
    assert auth_backend.transport == bearer_transport
    assert bearer_transport.scheme.model.flows.password.tokenUrl == "auth/jwt/login"  # type: ignore[attr-defined]


def test_jwt_strategy_creation() -> None:
    strategy = get_jwt_strategy()
    assert strategy.lifetime_seconds == 1800
