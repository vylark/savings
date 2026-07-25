"""Application database models package.

Re-exports all SQLAlchemy ORM models to ensure full model registration
on Base.metadata when imported by Alembic or application initialization.
"""

from src.models.user import User

__all__ = ["User"]
