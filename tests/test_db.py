from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_db_transaction_isolation_write(db_session: AsyncSession) -> None:
    """Verify database execution and table insertion within a transaction context."""
    await db_session.execute(text("CREATE TABLE test_isolation (id INT PRIMARY KEY, val TEXT);"))
    await db_session.execute(text("INSERT INTO test_isolation (id, val) VALUES (1, 'isolated');"))
    result = await db_session.execute(text("SELECT val FROM test_isolation WHERE id = 1;"))
    assert result.scalar() == "isolated"


async def test_db_transaction_isolation_rollback(db_session: AsyncSession) -> None:
    """Verify database connection isolation remains clean and unaffected by other tests."""
    result = await db_session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'test_isolation');")
    )
    assert result.scalar() is False
