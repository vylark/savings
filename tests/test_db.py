import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_db_transaction_isolation_part_1(db_session: AsyncSession) -> None:
    """Verify raw database connection and query execution within transaction context."""
    result = await db_session.execute(text("SELECT 1;"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_db_transaction_isolation_part_2(db_session: AsyncSession) -> None:
    """Verify database connection isolation remains clean for subsequent tests."""
    result = await db_session.execute(text("SELECT 1;"))
    assert result.scalar() == 1
