"""Integration tests for Multi-Factor Authentication (TOTP 2FA) endpoints and mandatory require_totp dependency."""

import httpx
import pyotp
import pytest


@pytest.mark.asyncio
async def test_2fa_setup_flow(authenticated_client: httpx.AsyncClient) -> None:
    """Tests /auth/2fa/setup endpoint returning secret, provisioning URI, and QR code payload."""
    response = await authenticated_client.post("/auth/2fa/setup")
    assert response.status_code == 200

    data = response.json()
    assert "secret" in data
    assert "provisioning_uri" in data
    assert "qr_code" in data
    assert data["qr_code"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_2fa_enable_and_verify_flow(authenticated_client: httpx.AsyncClient) -> None:
    """Tests 2FA activation with invalid and valid OTP passcodes."""
    # 1. Setup 2FA
    setup_res = await authenticated_client.post("/auth/2fa/setup")
    assert setup_res.status_code == 200
    secret = setup_res.json()["secret"]

    # 2. Attempt enable with invalid code -> 400
    bad_enable_res = await authenticated_client.post("/auth/2fa/enable", json={"code": "000000"})
    assert bad_enable_res.status_code == 400

    # 3. Enable with valid code -> 200
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()

    enable_res = await authenticated_client.post("/auth/2fa/enable", json={"code": valid_code})
    assert enable_res.status_code == 200
    assert enable_res.json()["status"] == "success"

    # 4. Verify code -> 200
    verify_code = totp.now()
    verify_res = await authenticated_client.post("/auth/2fa/verify", json={"code": verify_code})
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "success"

    # 5. Attempt setup again while 2FA is enabled -> 409 Conflict
    re_setup_res = await authenticated_client.post("/auth/2fa/setup")
    assert re_setup_res.status_code == 409
    assert "2FA is already enabled" in re_setup_res.json()["detail"]


@pytest.mark.asyncio
async def test_mandatory_require_totp_dependency(client: httpx.AsyncClient) -> None:
    """Tests mandatory 2FA enforcement on high-risk operations via require_totp dependency."""
    # 1. Register a new user
    user_payload = {
        "email": "mandatory2fa@example.com",
        "password": "SavingsPlatform2026!XyZ#9",
        "first_name": "Charlie",
        "last_name": "Brown",
        "tax_band": "basic",
    }
    await client.post("/auth/register", json=user_payload)

    login_res = await client.post(
        "/auth/jwt/login",
        data={"username": "mandatory2fa@example.com", "password": "SavingsPlatform2026!XyZ#9"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_res.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 2. Attempt high-risk action before 2FA is enabled -> 428 Precondition Required
    protected_res1 = await client.post("/auth/2fa/protected-action", headers=auth_headers)
    assert protected_res1.status_code == 428
    assert "2FA_SETUP_REQUIRED" in protected_res1.json()["detail"]

    # 3. Setup and enable 2FA
    setup_res = await client.post("/auth/2fa/setup", headers=auth_headers)
    secret = setup_res.json()["secret"]

    totp = pyotp.TOTP(secret)
    valid_code = totp.now()
    await client.post("/auth/2fa/enable", json={"code": valid_code}, headers=auth_headers)

    # 4. Attempt high-risk action without X-TOTP-Code header -> 401 Unauthorized
    protected_res2 = await client.post("/auth/2fa/protected-action", headers=auth_headers)
    assert protected_res2.status_code == 401

    # 5. Attempt high-risk action with invalid X-TOTP-Code header -> 401 Unauthorized
    bad_headers = {**auth_headers, "X-TOTP-Code": "000000"}
    protected_res3 = await client.post("/auth/2fa/protected-action", headers=bad_headers)
    assert protected_res3.status_code == 401

    # 6. Attempt high-risk action with valid X-TOTP-Code header -> 200 OK
    good_code = totp.now()
    good_headers = {**auth_headers, "X-TOTP-Code": good_code}
    protected_res4 = await client.post("/auth/2fa/protected-action", headers=good_headers)
    assert protected_res4.status_code == 200
    assert protected_res4.json()["status"] == "success"
