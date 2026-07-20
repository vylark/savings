import asyncio
import sys

from sqlalchemy import text

from src.db.session import AsyncSessionLocal


async def seed_development_data():
    """Populates local development database with baseline seeds if they don't exist."""
    print("Checking database for seeding...")
    async with AsyncSessionLocal() as session:
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
                    print("Seeding initial administrator user...")
                    # Placeholder query representing seeding logic.
                    # In real implementation:
                    # hashed_pwd = pwd_context.hash("adminpassword")
                    # session.add(User(email="admin@savings.local", hashed_password=hashed_pwd, ...))
                    print("Seeding placeholder (no data written yet).")
                else:
                    print("Database already contains user records. Skipping seed.")
            else:
                print("User table does not exist yet. Run migrations first.")
        except Exception as e:
            print(f"Error during seeding: {e}", file=sys.stderr)
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(seed_development_data())
