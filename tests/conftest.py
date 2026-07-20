import sys
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.db.session import get_db_session, get_engine, get_sessionmaker
from src.main import app

# Test Database Configuration
TEST_DB_NAME = "savings_test"
base_url, _ = settings.DATABASE_URL.rsplit("/", 1)
TEST_DATABASE_URL = f"{base_url}/{TEST_DB_NAME}"


async def create_test_db_if_not_exists() -> None:
    """Connect to default postgres DB and create the test database if it does not exist."""
    connection_string = base_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(connection_string)
    host = parsed.hostname or "127.0.0.1"
    if host == "localhost":
        host = "127.0.0.1"
    gsslib = "sspi" if sys.platform == "win32" else "gssapi"
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=host,
        port=parsed.port or 5432,
        database="postgres",
        gsslib=gsslib,
    )
    try:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = $1);",
            TEST_DB_NAME,
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}";')
            print(f"Created test database '{TEST_DB_NAME}' successfully.")
        else:
            print(f"Test database '{TEST_DB_NAME}' already exists.")
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_test_database() -> AsyncGenerator[None, None]:
    """Create the test database, run migrations once, and clean up at session end."""
    await create_test_db_if_not_exists()

    print("Running migrations on test database...")
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)

    def run_upgrade(connection: Connection) -> None:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    migration_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with migration_engine.connect() as conn:
        await conn.run_sync(run_upgrade)
    await migration_engine.dispose()

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    yield

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transaction-wrapped test database session.

    Rolls back all inserts/updates on completion to guarantee clean state.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        async with session_factory() as session:
            yield session
            await session.close()

        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def override_app_dependencies(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Override FastAPI's get_db_session dependency to yield the transaction-wrapped session."""

    async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _get_test_db
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Yield an HTTPX asynchronous client linked to the FastAPI application."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
