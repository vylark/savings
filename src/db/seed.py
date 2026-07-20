import asyncio
import logging

from sqlalchemy import text

from src.db.session import create_session

logger = logging.getLogger(__name__)


class SeedError(Exception):
    """Custom exception raised when database seeding fails."""


async def seed_development_data():
    """Populates local development database with baseline seeds if they don't exist."""
    logger.info("Checking database for seeding...")
    async with create_session() as session:
        # NOTE: Once the User model is introduced in Epic 1, replace this placeholder
        # SQL with SQLAlchemy queries that verify and create a default admin/test user.
        try:
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
                    # Placeholder query representing seeding logic.
                    # In real implementation:
                    # hashed_pwd = pwd_context.hash("adminpassword")
                    # session.add(User(email="admin@savings.local", hashed_password=hashed_pwd, ...))
                    logger.info("Seeding placeholder (no data written yet).")
                else:
                    logger.info("Database already contains user records. Skipping seed.")
            else:
                logger.info("User table does not exist yet. Run migrations first.")
        except Exception as exc:
            logger.exception("Error during seeding")
            raise SeedError("Failed to complete database seeding step") from exc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(seed_development_data())
