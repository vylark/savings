"""Integration tests for rate limiting middleware (slowapi)."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_health_check_unlimited(client: httpx.AsyncClient) -> None:
    """Verifies that health check endpoint remains un-throttled for container orchestration probes."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_login_rate_limit_exceeded(client: httpx.AsyncClient) -> None:
    """Verifies rate limit enforcement (HTTP 429) on POST /auth/jwt/login after 5 requests."""
    login_data = {
        "username": "ratelimit@example.com",
        "password": "WrongPassword123!",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # 5 allowed requests
    for _ in range(5):
        res = await client.post("/auth/jwt/login", data=login_data, headers=headers)
        assert res.status_code in (200, 400, 401)

    # 6th request triggers rate limit (HTTP 429)
    res_exceeded = await client.post("/auth/jwt/login", data=login_data, headers=headers)
    assert res_exceeded.status_code == 429


@pytest.mark.asyncio
async def test_2fa_setup_rate_limit_exceeded(authenticated_client: httpx.AsyncClient) -> None:
    """Verifies rate limit enforcement (HTTP 429) on POST /auth/2fa/setup after 5 requests."""
    # 5 allowed requests
    for _ in range(5):
        res = await authenticated_client.post("/auth/2fa/setup")
        assert res.status_code == 200

    # 6th request triggers rate limit (HTTP 429)
    res_exceeded = await authenticated_client.post("/auth/2fa/setup")
    assert res_exceeded.status_code == 429


@pytest.mark.asyncio
async def test_2fa_verify_rate_limit_exceeded(authenticated_client: httpx.AsyncClient) -> None:
    """Verifies brute-force protection (HTTP 429) on POST /auth/2fa/verify after 5 requests."""
    import pyotp

    # 1. Setup and enable 2FA so verification endpoint can be exercised
    setup_res = await authenticated_client.post("/auth/2fa/setup")
    assert setup_res.status_code == 200
    secret = setup_res.json()["secret"]

    totp = pyotp.TOTP(secret)
    enable_res = await authenticated_client.post("/auth/2fa/enable", json={"code": totp.now()})
    assert enable_res.status_code == 200

    # 2. Attempt 5 invalid verify requests
    for _ in range(5):
        res = await authenticated_client.post("/auth/2fa/verify", json={"code": "000000"})
        assert res.status_code == 400

    # 3. 6th attempt triggers rate limit (HTTP 429)
    res_exceeded = await authenticated_client.post("/auth/2fa/verify", json={"code": "000000"})
    assert res_exceeded.status_code == 429
