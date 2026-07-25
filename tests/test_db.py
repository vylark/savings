"""Integration tests for database transaction isolation and session rollback behavior."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


async def test_db_transaction_isolation(db_session: AsyncSession, test_engine: AsyncEngine) -> None:
    """Verify database execution, table insertion, and isolation from external connections."""
    await db_session.execute(text("CREATE TABLE test_isolation (id INT PRIMARY KEY, val TEXT);"))
    await db_session.execute(text("INSERT INTO test_isolation (id, val) VALUES (1, 'isolated');"))

    # Verify write is visible within the active transaction session
    result = await db_session.execute(text("SELECT val FROM test_isolation WHERE id = 1;"))
    assert result.scalar() == "isolated"

    # Verify uncommitted transaction writes are isolated from external connections
    async with test_engine.connect() as conn:
        ext_result = await conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'test_isolation');")
        )
        assert ext_result.scalar() is False
