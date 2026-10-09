"""Physical account and sharing permissions ORM models module.

Defines the SQLAlchemy entities representing financial institutions, real-world asset accounts,
multi-user sharing relationships, and balance reconciliation audit records.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.constants import AccountRole, Currency, TaxWrapper
from src.db.base import Base

if TYPE_CHECKING:
    from src.models.user import User


class Institution(Base):
    """Financial institution or banking provider entity (e.g., Barclays, Vanguard, Monzo).

    Attributes:
        id: Primary key UUID.
        name: Official provider name (Unique).
        code: Optional machine-readable identifier (e.g., 'BARCLAYS_UK', 'VANGUARD_UK').
        logo_url: Optional asset URI for UI display.
        parent_institution_id: Optional self-referential foreign key linking sub-brands/divisions
            to their parent banking license/group (e.g. First Direct -> HSBC UK Bank plc)
            for FSCS £85,000 protection calculations.
        created_at: Timestamp when provider was added to catalog.
    """

    __tablename__ = "institution"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institution.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    parent_institution: Mapped["Institution | None"] = relationship(
        "Institution",
        remote_side=[id],
        back_populates="sub_institutions",
    )
    sub_institutions: Mapped[list["Institution"]] = relationship(
        "Institution",
        back_populates="parent_institution",
    )
    physical_accounts: Mapped[list["PhysicalAccount"]] = relationship(
        "PhysicalAccount",
        back_populates="institution",
    )


class PhysicalAccount(Base):
    """Physical account entity representing a real-world bank, broker, or depository asset.

    Attributes:
        id: Primary key UUID.
        name: User-defined label (e.g., 'Everyday Saver', 'Stocks & Shares ISA').
        institution_id: Foreign key referencing the parent Institution entity.
        tax_wrapper: Legal tax classification wrapper.
        currency: Base denomination currency for the account.
        interest_rate: Annual percentage interest rate (e.g. 0.0450 for 4.50%), nullable.
        access_delay_days: Number of business days required to withdraw funds (0 for instant access).
        maturity_date: Optional fixed-term maturity date for fixed rate bonds/ISAs.
        created_at: Timestamp when the account record was initialized.
        updated_at: Timestamp when metadata was last modified.
    """

    __tablename__ = "physical_account"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institution.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    tax_wrapper: Mapped[TaxWrapper] = mapped_column(
        Enum(TaxWrapper, native_enum=False, length=20),
        nullable=False,
    )
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, native_enum=False, length=3),
        nullable=False,
        default=Currency.GBP,
    )
    interest_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=True,
    )
    access_delay_days: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )
    maturity_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    institution: Mapped["Institution"] = relationship(
        "Institution",
        back_populates="physical_accounts",
    )
    shares: Mapped[list["PhysicalAccountShare"]] = relationship(
        "PhysicalAccountShare",
        back_populates="physical_account",
        cascade="all, delete-orphan",
    )
    reconciliations: Mapped[list["ReconciliationEvent"]] = relationship(
        "ReconciliationEvent",
        back_populates="physical_account",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("access_delay_days >= 0", name="ck_physical_account_delay_non_negative"),
        CheckConstraint("interest_rate >= 0.0000", name="ck_physical_account_interest_non_negative"),
    )


class PhysicalAccountShare(Base):
    """Many-to-Many sharing link connecting users to physical accounts with specific roles.

    Attributes:
        id: Primary key UUID.
        user_id: Foreign key to User entity receiving access.
        physical_account_id: Foreign key to shared PhysicalAccount.
        role: RBAC authorization tier (OWNER, CO_OWNER, ALLOCATOR).
        created_at: Timestamp when access was granted.
    """

    __tablename__ = "physical_account_share"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    physical_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("physical_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[AccountRole] = mapped_column(
        Enum(AccountRole, native_enum=False, length=20),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    physical_account: Mapped["PhysicalAccount"] = relationship(
        "PhysicalAccount",
        back_populates="shares",
    )
    user: Mapped["User"] = relationship("User")

    __table_args__ = (UniqueConstraint("user_id", "physical_account_id", name="uq_user_physical_account_share"),)


class ReconciliationEvent(Base):
    """Audit log entry capturing point-in-time bank balance submissions and calculated drift.

    Attributes:
        id: Primary key UUID.
        physical_account_id: Target account reconciled.
        user_id: Actor who submitted the statement balance.
        submitted_balance: Real-world balance reported by bank statement.
        calculated_drift: Difference between submitted balance and ledger balance.
        timestamp: Time of reconciliation action.
    """

    __tablename__ = "reconciliation_event"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    physical_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("physical_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    submitted_balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=False,
    )
    calculated_drift: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    physical_account: Mapped["PhysicalAccount"] = relationship(
        "PhysicalAccount",
        back_populates="reconciliations",
    )
    user: Mapped["User"] = relationship("User")
