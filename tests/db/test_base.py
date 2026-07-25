"""Unit tests for SQLAlchemy base metadata initialization."""

from src.db.base import Base


def test_base_metadata_initialized() -> None:
    """Verify that SQLAlchemy declarative Base metadata object is initialized."""
    assert Base.metadata is not None
