import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_db_transaction_isolation_part_1(db_session: AsyncSession) -> None:
    """Verify raw database execution and temporary table insertion within transaction context."""
    await db_session.execute(text("CREATE TEMP TABLE test_isolation (id INT PRIMARY KEY, val TEXT);"))
    await db_session.execute(text("INSERT INTO test_isolation (id, val) VALUES (1, 'isolated');"))
    result = await db_session.execute(text("SELECT val FROM test_isolation WHERE id = 1;"))
    assert result.scalar() == "isolated"


@pytest.mark.asyncio
async def test_db_transaction_isolation_part_2(db_session: AsyncSession) -> None:
    """Verify database connection isolation remains clean and rolled back for subsequent tests."""
    result = await db_session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'test_isolation');")
    )
    assert result.scalar() is False
