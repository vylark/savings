import ssl

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings

# SSL configurations for secure database connection
connect_args = {}
if settings.DATABASE_SSL:
    ctx = ssl.create_default_context()
    if settings.DATABASE_CA_FILE:
        ctx.load_verify_locations(cafile=settings.DATABASE_CA_FILE)
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
