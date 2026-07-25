"""SQLAlchemy declarative base module.

Provides the foundational DeclarativeBase metadata registry inherited by all application ORM models.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models in the application."""

    pass
