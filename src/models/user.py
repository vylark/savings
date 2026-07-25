"""User database model definition module.

Contains the SQLAlchemy User ORM entity representing user credentials and profile data.
"""

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.constants import TaxBand
from src.db.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """User database entity representing authenticated system accounts.

    Inherits core identity fields (id, email, hashed_password, is_active, is_superuser,
    is_verified) from SQLAlchemyBaseUserTableUUID and adds custom user profile fields.

    Attributes:
        first_name: Given name of the user.
        last_name: Surname of the user.
        tax_band: Tax band classification (defaults to 'basic').
    """

    __tablename__ = "user"

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_band: Mapped[TaxBand] = mapped_column(
        Enum(TaxBand, native_enum=False, length=20),
        default=TaxBand.BASIC,
        nullable=False,
    )
