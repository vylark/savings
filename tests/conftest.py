"""Pytest configuration and fixture definitions for application test suite."""

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
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.core.constants import TaxBand
from src.core.limiter import limiter
from src.core.mail import clear_outbox
from src.db.seed import seed_institutions
from src.db.session import get_db_session, get_engine, get_sessionmaker
from src.main import app
from src.models.physical_account import Institution

# Test Database Configuration
TEST_DB_NAME = "savings_test"
base_url, _ = settings.DATABASE_URL.rsplit("/", 1)
TEST_DATABASE_URL = f"{base_url}/{TEST_DB_NAME}"


@pytest.fixture(scope="function", autouse=True)
def auto_reset_test_state() -> None:
    """Automatically resets rate limiter and clears email outbox before each test execution."""
    clear_outbox()
    limiter.reset()


async def create_test_db_if_not_exists() -> None:
    """Connect to default postgres DB and create the test database if it does not exist."""
    # SQLAlchemy cannot execute CREATE DATABASE because it wraps statements
    # in implicit transactions. asyncpg is used here for this DDL-only operation.
    connection_string = base_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(connection_string)
    host = parsed.hostname or "127.0.0.1"
    # asyncpg on Windows fails to resolve 'localhost' automatically in some socket configurations
    if host == "localhost":
        host = "127.0.0.1"
    connect_kwargs: dict = {
        "user": parsed.username,
        "password": parsed.password,
        "host": host,
        "port": parsed.port or 5432,
        "database": "postgres",
    }
    if sys.platform == "win32":
        connect_kwargs["gsslib"] = None
    conn = await asyncpg.connect(**connect_kwargs)
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


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database() -> AsyncGenerator[None, None]:
    """Create test database and run migrations once per session.

    Downgrades to base and upgrades to head on each test session to guarantee a clean schema.
    """
    await create_test_db_if_not_exists()

    print("Running migrations on test database...")
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)

    def run_migrations(connection: Connection) -> None:
        alembic_cfg.attributes["connection"] = connection
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")

    migration_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with migration_engine.connect() as conn:
        await conn.run_sync(run_migrations)
    await migration_engine.dispose()

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    yield

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest_asyncio.fixture(scope="session")
async def test_engine(setup_test_database: None) -> AsyncGenerator[AsyncEngine, None]:
    """Yield a session-scoped async engine for testing."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a transaction-wrapped test database session.

    Rolls back all inserts/updates on completion to guarantee clean state.
    """
    async with test_engine.connect() as connection:
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

        await transaction.rollback()


@pytest_asyncio.fixture(scope="function")
async def seeded_institutions(db_session: AsyncSession) -> list[Institution]:
    """Pre-seeds standard financial institutions catalog within the test transaction rollback boundary.

    Args:
        db_session: Active transaction-wrapped test database session.

    Returns:
        List of populated Institution ORM entities.
    """
    return await seed_institutions(db_session, commit=False)


@pytest_asyncio.fixture(scope="function")
async def override_app_dependencies(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Override FastAPI's get_db_session dependency to yield the transaction-wrapped session."""

    async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest_asyncio.fixture(scope="function")
async def client(override_app_dependencies: None) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Yield an HTTPX asynchronous client linked to the FastAPI application."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest_asyncio.fixture(scope="function")
async def authenticated_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Yield an HTTPX client pre-authenticated with a valid JWT Bearer token."""
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
    access_token = login_response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {access_token}"
    return client
