"""Integration tests for application endpoints including authentication and user management."""

import pytest
from httpx import AsyncClient

from src.core.constants import TaxBand


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """Verify that the health check endpoint returns 200 OK with healthy status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_user_registration_success(client: AsyncClient) -> None:
    """Verify successful registration of a new user with custom fields."""
    register_payload = {
        "email": "user@example.com",
        "password": "SavingsPlatform2026!XyZ#9",
        "first_name": "Jane",
        "last_name": "Doe",
        "tax_band": TaxBand.HIGHER.value,
    }
    reg_response = await client.post("/auth/register", json=register_payload)
    assert reg_response.status_code == 201
    user_data = reg_response.json()
    assert "id" in user_data
    assert user_data["email"] == "user@example.com"
    assert user_data["first_name"] == "Jane"
    assert user_data["last_name"] == "Doe"
    assert user_data["tax_band"] == TaxBand.HIGHER.value


@pytest.mark.asyncio
async def test_user_registration_duplicate_email_returns_400(client: AsyncClient) -> None:
    """Verify that attempting to register with an existing email returns HTTP 400."""
    import uuid
    unique_email = f"duplicate-{uuid.uuid4()}@example.com"
    register_payload = {
        "email": unique_email,
        "password": "SavingsPlatform2026!XyZ#9",
        "first_name": "Alice",
        "last_name": "Smith",
        "tax_band": TaxBand.BASIC.value,
    }
    res1 = await client.post("/auth/register", json=register_payload)
    assert res1.status_code == 201

    res2 = await client.post("/auth/register", json=register_payload)
    assert res2.status_code == 400
    assert "REGISTER_USER_ALREADY_EXISTS" in str(res2.json())


@pytest.mark.asyncio
async def test_user_registration_weak_password_returns_400(client: AsyncClient) -> None:
    """Verify that user registration with a weak/dictionary password returns HTTP 400."""
    weak_payload = {
        "email": "weakpass@example.com",
        "password": "password123456",
        "first_name": "Weak",
        "last_name": "User",
        "tax_band": TaxBand.BASIC.value,
    }
    response = await client.post("/auth/register", json=weak_payload)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_user_registration_missing_required_fields_returns_422(client: AsyncClient) -> None:
    """Verify that user registration missing required fields returns HTTP 422."""
    incomplete_payload = {
        "email": "incomplete@example.com",
        "password": "SavingsPlatform2026!XyZ#9",
    }
    response = await client.post("/auth/register", json=incomplete_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_user_registration_invalid_email_returns_422(client: AsyncClient) -> None:
    """Verify that user registration with a malformed email address returns HTTP 422."""
    invalid_email_payload = {
        "email": "not-an-email",
        "password": "SavingsPlatform2026!XyZ#9",
        "first_name": "Jane",
        "last_name": "Doe",
    }
    response = await client.post("/auth/register", json=invalid_email_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_user_registration_invalid_tax_band_returns_422(client: AsyncClient) -> None:
    """Verify that user registration with an invalid tax band returns a 422 Unprocessable Entity error."""
    invalid_reg_payload = {
        "email": "user2@example.com",
        "password": "SavingsPlatform2026!XyZ#9",
        "first_name": "John",
        "last_name": "Smith",
        "tax_band": "invalid_band",
    }
    invalid_reg_response = await client.post("/auth/register", json=invalid_reg_payload)
    assert invalid_reg_response.status_code == 422


@pytest.mark.asyncio
async def test_users_me_unauthenticated_returns_401(client: AsyncClient) -> None:
    """Verify that requesting the current user profile without authentication returns 401 Unauthorized."""
    unauth_response = await client.get("/users/me")
    assert unauth_response.status_code == 401


@pytest.mark.asyncio
async def test_jwt_login_success(client: AsyncClient) -> None:
    """Verify that valid user credentials yield a JWT bearer access token."""
    register_payload = {
        "email": "user@example.com",
        "password": "SavingsPlatform2026!XyZ#9",
        "first_name": "Jane",
        "last_name": "Doe",
        "tax_band": TaxBand.HIGHER.value,
    }
    await client.post("/auth/register", json=register_payload)

    login_data = {
        "username": "user@example.com",
        "password": "SavingsPlatform2026!XyZ#9",
    }
    login_response = await client.post(
        "/auth/jwt/login",
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_response.status_code == 200
    token_data = login_response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_user_profile_read_and_update(authenticated_client: AsyncClient) -> None:
    """Verify reading and updating the profile of an authenticated user via /users/me."""
    me_response = await authenticated_client.get("/users/me")
    assert me_response.status_code == 200
    profile_data = me_response.json()
    assert profile_data["email"] == "user@example.com"
    assert profile_data["first_name"] == "Jane"

    patch_payload = {"first_name": "Janet", "tax_band": TaxBand.ADDITIONAL.value}
    patch_response = await authenticated_client.patch("/users/me", json=patch_payload)
    assert patch_response.status_code == 200
    updated_data = patch_response.json()
    assert updated_data["first_name"] == "Janet"
    assert updated_data["tax_band"] == TaxBand.ADDITIONAL.value
