from src.core.constants import TaxBand
from src.models.user import User


def test_user_model_attributes() -> None:
    user = User(
        email="test@example.com",
        # arbitrary string -- testing ORM attribute presence, not password hashing logic
        hashed_password="hashed_password_string",
        first_name="Jane",
        last_name="Smith",
        tax_band=TaxBand.BASIC,
    )
    assert user.email == "test@example.com"
    assert user.first_name == "Jane"
    assert user.last_name == "Smith"
    assert user.tax_band == TaxBand.BASIC
    assert user.__tablename__ == "user"
