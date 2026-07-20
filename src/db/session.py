import ssl
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Create and cache AsyncEngine instance based on application settings.

    Note: This function is cached for the process lifetime via @lru_cache.
    Test suites that patch `settings` must call `get_engine.cache_clear()`
    in teardown to avoid operating against a stale engine and connection pool.
    """
    connect_args = {}
    if settings.DATABASE_SSL:
        ctx = ssl.create_default_context()
        if settings.DATABASE_CA_FILE:
            ctx.load_verify_locations(cafile=settings.DATABASE_CA_FILE)
        connect_args["ssl"] = ctx

    return create_async_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        echo=settings.ENVIRONMENT == "development",
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Create and cache async_sessionmaker instance.

    Note: This function is cached for the process lifetime via @lru_cache.
    Test suites must call `get_engine.cache_clear()` and
    `get_sessionmaker.cache_clear()` in teardown to avoid session factory
    instances bound to a stale engine.
    """
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


def create_session() -> AbstractAsyncContextManager[AsyncSession]:
    """Helper function to instantiate a new AsyncSession.

    Must be used as an async context manager:
        async with create_session() as session: ...
    """
    return get_sessionmaker()()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to yield database session to FastAPI routers."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
