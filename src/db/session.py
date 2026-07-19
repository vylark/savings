import ssl
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.config import settings

# Neon serverless PostgreSQL requires SSL. We apply SSL configurations conditionally.
connect_args = {}
if settings.DATABASE_SSL:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # In production, swap with server CA files if strict verification is preferred
    connect_args["ssl"] = ctx

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=settings.ENVIRONMENT == "development",
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db_session() -> AsyncSession:
    """Dependency to yield database session to FastAPI routers."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
