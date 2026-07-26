"""Integration tests for transactional email transport and account verification flow."""

import httpx
import pytest

from src.core.mail import clear_outbox, outbox


@pytest.mark.asyncio
async def test_registration_dispatches_verification_email(client: httpx.AsyncClient) -> None:
    """Verifies that user registration dispatches welcome email and verification token into outbox."""
    clear_outbox()

    payload = {
        "email": "verify.user@example.com",
        "password": "StrongPassword123!",
        "first_name": "Alice",
        "last_name": "Smith",
        "tax_band": "basic",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201

    assert len(outbox) >= 2
    welcome_email = outbox[0]
    assert welcome_email["recipient"] == "verify.user@example.com"
    assert "Welcome to Savings Platform" in welcome_email["subject"]

    verify_email = outbox[1]
    assert verify_email["recipient"] == "verify.user@example.com"
    assert "Account Verification Token" in verify_email["subject"]
    assert "token is:" in verify_email["body"]


@pytest.mark.asyncio
async def test_email_verification_flow(client: httpx.AsyncClient) -> None:
    """Verifies account token verification transitioning user to is_verified=True state."""
    clear_outbox()

    # 1. Register user
    reg_payload = {
        "email": "verify.flow@example.com",
        "password": "StrongPassword123!",
        "first_name": "Bob",
        "last_name": "Jones",
        "tax_band": "basic",
    }
    reg_res = await client.post("/auth/register", json=reg_payload)
    assert reg_res.status_code == 201

    # 2. Request verification token
    req_verify_res = await client.post("/auth/request-verify-token", json={"email": "verify.flow@example.com"})
    assert req_verify_res.status_code == 202

    # Extract token from outbox
    assert len(outbox) >= 1
    email_body = outbox[-1]["body"]
    token = email_body.split("token is: ")[-1].strip()

    # 3. Verify account
    verify_res = await client.post("/auth/verify", json={"token": token})
    assert verify_res.status_code == 200

    # 4. Login and verify is_verified field in /users/me
    login_res = await client.post(
        "/auth/jwt/login",
        data={"username": "verify.flow@example.com", "password": "StrongPassword123!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_res.status_code == 200
    token_str = login_res.json()["access_token"]

    me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {token_str}"})
    assert me_res.status_code == 200
    assert me_res.json()["is_verified"] is True
