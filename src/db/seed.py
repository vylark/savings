"""Database seeding module for local development and initial institution catalog population."""

import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import create_session
from src.models.physical_account import Institution

logger = logging.getLogger(__name__)

INITIAL_INSTITUTIONS: tuple[dict[str, str | None], ...] = (
    {"name": "HSBC UK", "parent_name": None},
    {"name": "First Direct", "parent_name": "HSBC UK"},
    {"name": "Lloyds Bank", "parent_name": None},
    {"name": "Scottish Widows", "parent_name": "Lloyds Bank"},
    {"name": "Barclays", "parent_name": None},
    {"name": "Vanguard", "parent_name": None},
    {"name": "Monzo", "parent_name": None},
    {"name": "Trading 212", "parent_name": None},
    {"name": "Interactive Investor", "parent_name": None},
)


class SeedError(Exception):
    """Custom exception raised when database seeding fails."""


async def seed_institutions(session: AsyncSession) -> list[Institution]:
    """Idempotently populates the financial institutions catalog with standard providers.

    Inserts root institutions first, then links subsidiary brands (e.g., First Direct -> HSBC UK,
    Scottish Widows -> Lloyds Bank) via parent_institution_id.

    Args:
        session: Active asynchronous SQLAlchemy database session.

    Returns:
        List of all Institution entities present in the catalog after seeding.
    """
    existing_result = await session.execute(select(Institution))
    existing_by_name: dict[str, Institution] = {inst.name: inst for inst in existing_result.scalars().all()}

    # First pass: create top-level institutions (no parent_name)
    for item in INITIAL_INSTITUTIONS:
        name = item["name"]
        if item["parent_name"] is None and name is not None and name not in existing_by_name:
            inst = Institution(name=name)
            session.add(inst)
            existing_by_name[name] = inst

    await session.flush()

    # Second pass: create child institutions with parent_institution_id
    for item in INITIAL_INSTITUTIONS:
        name = item["name"]
        parent_name = item["parent_name"]
        if parent_name is not None and name is not None and name not in existing_by_name:
            parent_inst = existing_by_name.get(parent_name)
            inst = Institution(
                name=name,
                parent_institution_id=parent_inst.id if parent_inst else None,
            )
            session.add(inst)
            existing_by_name[name] = inst

    await session.commit()
    return list(existing_by_name.values())


async def seed_development_data() -> None:
    """Populates local development database with baseline seeds if they don't exist."""
    logger.info("Checking database for seeding...")
    async with create_session() as session:
        try:
            # Check if institution table exists and seed baseline financial institutions
            inst_table_result = await session.execute(
                text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'institution');")
            )
            if inst_table_result.scalar():
                await seed_institutions(session)
                logger.info("Institution catalog verified/seeded successfully.")

            # Simple check if users table exists and is empty
            result = await session.execute(
                text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'user');")
            )
            table_exists = result.scalar()

            if table_exists:
                user_count_result = await session.execute(text('SELECT COUNT(*) FROM "user";'))
                user_count = user_count_result.scalar()
                if user_count == 0:
                    logger.info("Seeding initial administrator user...")
                    logger.info("Seeding placeholder (no data written yet).")
                else:
                    logger.info("Database already contains user records. Skipping seed.")
            else:
                logger.info("User table does not exist yet. Run migrations first.")
        except Exception as exc:
            logger.error("Error during seeding: %s", exc)
            raise SeedError("Failed to complete database seeding step") from exc


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(seed_development_data())
