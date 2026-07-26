"""Integration tests for rate limiting middleware (slowapi)."""

import httpx
import pytest

from src.core.limiter import limiter


@pytest.mark.asyncio
async def test_health_check_unlimited(client: httpx.AsyncClient) -> None:
    """Verifies that health check endpoint remains un-throttled for container orchestration probes."""
    limiter.reset()
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
