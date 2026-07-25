import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_user_registration_success(client: AsyncClient) -> None:
    register_payload = {
        "email": "user@example.com",
        "password": "StrongPassword123!",
        "first_name": "Jane",
        "last_name": "Doe",
        "tax_band": "higher",
    }
    reg_response = await client.post("/auth/register", json=register_payload)
    assert reg_response.status_code == 201
    user_data = reg_response.json()
    assert "id" in user_data
    assert user_data["email"] == "user@example.com"
    assert user_data["first_name"] == "Jane"
    assert user_data["last_name"] == "Doe"
    assert user_data["tax_band"] == "higher"


@pytest.mark.asyncio
async def test_user_registration_invalid_tax_band_returns_422(client: AsyncClient) -> None:
    invalid_reg_payload = {
        "email": "user2@example.com",
        "password": "StrongPassword123!",
        "first_name": "John",
        "last_name": "Smith",
        "tax_band": "invalid_band",
    }
    invalid_reg_response = await client.post("/auth/register", json=invalid_reg_payload)
    assert invalid_reg_response.status_code == 422


@pytest.mark.asyncio
async def test_users_me_unauthenticated_returns_401(client: AsyncClient) -> None:
    unauth_response = await client.get("/users/me")
    assert unauth_response.status_code == 401


@pytest.mark.asyncio
async def test_jwt_login_success(client: AsyncClient) -> None:
    register_payload = {
        "email": "user@example.com",
        "password": "StrongPassword123!",
        "first_name": "Jane",
        "last_name": "Doe",
        "tax_band": "higher",
    }
    await client.post("/auth/register", json=register_payload)

    login_data = {
        "username": "user@example.com",
        "password": "StrongPassword123!",
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
async def test_user_profile_read_and_update(client: AsyncClient) -> None:
    register_payload = {
        "email": "user@example.com",
        "password": "StrongPassword123!",
        "first_name": "Jane",
        "last_name": "Doe",
        "tax_band": "higher",
    }
    await client.post("/auth/register", json=register_payload)

    login_data = {
        "username": "user@example.com",
        "password": "StrongPassword123!",
    }
    login_response = await client.post(
        "/auth/jwt/login",
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    access_token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    me_response = await client.get("/users/me", headers=headers)
    assert me_response.status_code == 200
    profile_data = me_response.json()
    assert profile_data["email"] == "user@example.com"
    assert profile_data["first_name"] == "Jane"

    patch_payload = {"first_name": "Janet", "tax_band": "additional"}
    patch_response = await client.patch("/users/me", json=patch_payload, headers=headers)
    assert patch_response.status_code == 200
    updated_data = patch_response.json()
    assert updated_data["first_name"] == "Janet"
    assert updated_data["tax_band"] == "additional"
