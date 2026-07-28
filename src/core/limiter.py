"""Rate limiting middleware setup module.

Provides a slowapi Limiter instance initialized with Redis or in-memory backend storage
and configured with remote IP address keying.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.config import settings

# Initialize limiter with Redis storage if REDIS_URL configured, otherwise fallback to in-memory
storage_uri = settings.REDIS_URL if settings.REDIS_URL else "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=storage_uri,
    default_limits=[],
)
