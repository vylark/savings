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
