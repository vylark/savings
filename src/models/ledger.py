"""Unified Ledger database models module.

Contains the TransactionEvent and LedgerEntry ORM entities representing the immutable
unified allocation ledger.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.constants import Currency
from src.db.base import Base

if TYPE_CHECKING:
    from src.models.physical_account import PhysicalAccount
    from src.models.user import User


class TransactionEvent(Base):
    """Logical grouping entity for atomic ledger transactions.

    Acts as an audit wrapper for all ledger entries created in a single operation
    (e.g., deposit, withdrawal, internal transfer, or reconciliation true-up).

    Attributes:
        id: Primary key UUID.
        description: Human-readable transaction description.
        timestamp: UTC timestamp when transaction occurred.
        is_reversal: True if this transaction reverses an earlier transaction.
        reversed_by_id: Optional foreign key set on the original transaction pointing
            to the reversing TransactionEvent.
    """

    __tablename__ = "transaction_event"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    is_reversal: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    reversed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transaction_event.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )


class LedgerEntry(Base):
    """Atomic ledger entry recording a fractional slice of funds.

    Strictly immutable once written. All balance adjustments must occur via new entries.

    Attributes:
        id: Primary key UUID.
        transaction_id: Foreign key referencing the parent TransactionEvent.
        physical_account_id: Foreign key referencing the target PhysicalAccount.
        virtual_account_id: UUID referencing the target VirtualAccount (or unallocated bucket).
        user_id: Foreign key referencing the owning/allocating User.
        currency: ISO currency denomination of the entry.
        amount: Signed monetary amount (precision 18, scale 2).
        created_at: UTC timestamp when the entry was recorded.
    """

    __tablename__ = "ledger_entry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transaction_event.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    physical_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("physical_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    virtual_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, native_enum=False, length=3),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    transaction: Mapped["TransactionEvent"] = relationship(
        "TransactionEvent",
        back_populates="entries",
    )
    physical_account: Mapped["PhysicalAccount"] = relationship(
        "PhysicalAccount",
        foreign_keys=[physical_account_id],
    )
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
    )

    __table_args__ = (
        # Fast physical account total balance aggregation
        Index("ix_ledger_physical_currency", "physical_account_id", "currency"),
        # Fast virtual goal total balance aggregation
        Index("ix_ledger_virtual_currency", "virtual_account_id", "currency"),
        # Allocator-specific filtered physical balance queries
        Index("ix_ledger_physical_user", "physical_account_id", "user_id"),
        # User unallocated bucket deficit checks
        Index("ix_ledger_user_virtual", "user_id", "virtual_account_id"),
    )
