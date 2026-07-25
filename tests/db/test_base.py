from src.db.base import Base


def test_base_metadata_initialized() -> None:
    assert Base.metadata is not None
