# Unified Ledger Schema Design & Query Performance Specification

This document outlines the architectural foundations, mathematical invariants, database schema design, and query optimization patterns for the Unified Ledger. It serves as the authoritative blueprint for the double-entry accounting engine powering Epic 2 (Physical Accounts Management) and Epic 4 (Transactions & Ledger).

---

## 1. Architectural Overview & The Parity Rule

The application requires tracking fractional allocations of physical assets (e.g., bank accounts, brokerages) into virtual goals (e.g., Emergency Fund, House Deposit, Wedding) across multiple users.

Rather than maintaining two separate, asynchronous ledgers (one for physical bank accounts and one for virtual envelopes), we implement a **Unified Single-Entry Ledger Model**. Every row in the ledger represents an atomic slice of money that simultaneously binds:
1. **Physical Location**: Where the money physically resides (`physical_account_id`).
2. **Virtual Purpose**: What financial goal or envelope the money is earmarked for (`virtual_account_id`).
3. **Legal Ownership**: Which user owns or allocated that slice (`user_id`).
4. **Currency**: Explicit currency code (`currency`) to avoid cross-currency aggregation errors.
5. **Quantity**: Signed decimal amount (`amount`).

```mermaid
graph TD
    subgraph Transaction Context
        TE[TransactionEvent]
    end
    
    subgraph Unified Ledger Entries
        LE1[LedgerEntry 1]
        LE2[LedgerEntry 2]
    end
    
    subgraph Dimensions Bound to Each Slice
        PA["Physical Account<br/>Where it lives"]
        VA["Virtual Account<br/>What it is for"]
        U["User<br/>Who owns it"]
        C["Currency<br/>GBP / USD / EUR"]
        AMT["Amount<br/>+/- Numeric"]
    end

    TE -->|1 to N| LE1
    TE -->|1 to N| LE2
    LE1 -.-> PA
    LE1 -.-> VA
    LE1 -.-> U
    LE1 -.-> C
    LE1 -.-> AMT
```

### The Parity Rule (Mathematical Invariant)
Because every single ledger entry carries both `physical_account_id` and `virtual_account_id`, the system guarantees by construction that within any given currency $C$:
$$\sum_{a \in \text{PhysicalAccounts}(C)} \text{Balance}(a) = \sum_{v \in \text{VirtualAccounts}(C)} \text{Balance}(v)$$

* **Physical Account Balance**:
  $$\text{Balance}_{\text{physical}}(A) = \sum \text{amount} \quad \text{WHERE } \text{physical\_account\_id} = A$$
* **Virtual Account Balance**:
  $$\text{Balance}_{\text{virtual}}(V) = \sum \text{amount} \quad \text{WHERE } \text{virtual\_account\_id} = V$$
* **User's Allocated Balance in an Account**:
  $$\text{Balance}_{\text{allocator}}(A, U) = \sum \text{amount} \quad \text{WHERE } \text{physical\_account\_id} = A \text{ AND } \text{user\_id} = U$$

---

## 2. Database Schema Definition

### Data Models (SQLAlchemy 2.0 Specification)

**Target Module**: `src/models/ledger.py`

```python
"""Unified Ledger database models module.

Contains the TransactionEvent and LedgerEntry ORM entities representing the immutable
double-entry accounting ledger.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.constants import CurrencyType
from src.db.base import Base

if TYPE_CHECKING:
    from src.models.physical_account import PhysicalAccount
    from src.models.user import User


class TransactionEvent(Base):
    """Logical grouping entity for atomic ledger transactions.

    Acts as an audit wrapper for all ledger entries created in a single operation
    (e.g., deposit, withdrawal, internal transfer, or reconciliation true-up).
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
    reversed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
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
        nullable=False,  # References virtual_account.id once Epic 3 is added
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency: Mapped[CurrencyType] = mapped_column(
        Enum(CurrencyType, native_enum=False, length=3),
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
```

---

## 3. Query Patterns & SQL Optimization

To guarantee sub-10ms response times for balance reads, specific composite indexes are established and raw SQL aggregation patterns are verified.

### Query 1: Physical Account Total Balance (for `OWNER` / `CO_OWNER`)
```sql
SELECT COALESCE(SUM(amount), 0.00) AS total_balance
FROM ledger_entry
WHERE physical_account_id = :physical_account_id
  AND currency = :currency;
```
*Index Used*: `ix_ledger_physical_currency (physical_account_id, currency)` (Index Only Scan).

### Query 2: Allocator-Specific Balance (for `ALLOCATOR`)
```sql
SELECT COALESCE(SUM(amount), 0.00) AS allocated_balance
FROM ledger_entry
WHERE physical_account_id = :physical_account_id
  AND user_id = :user_id
  AND currency = :currency;
```
*Index Used*: `ix_ledger_physical_user (physical_account_id, user_id)` (Bitmap Index Scan).

### Query 3: Multi-Account Dashboard Aggregation (Batch Load)
When loading `GET /physical-accounts/`, avoid $N+1$ queries by grouping:
```sql
SELECT 
    physical_account_id,
    COALESCE(SUM(amount), 0.00) AS balance
FROM ledger_entry
WHERE physical_account_id = ANY(:account_ids)
GROUP BY physical_account_id;
```

### Query 4: Unallocated Deficit Freeze Check
```sql
SELECT COALESCE(SUM(amount), 0.00) AS unallocated_balance
FROM ledger_entry
WHERE user_id = :user_id
  AND virtual_account_id = :unallocated_virtual_id;
```
If `unallocated_balance < 0`, the **Deficit Freeze Constraint** is active.

---

## 4. Multi-Currency & Precision Constraints

1. **Precision & Scale**: All monetary balances use `NUMERIC(18, 2)` (or Python `decimal.Decimal`). Floating-point arithmetic (`float`) is strictly prohibited.
2. **Strict Currency Homogeneity**:
   * Every `LedgerEntry.currency` MUST match its associated `PhysicalAccount.currency`.
   * All `LedgerEntry` records within a single `TransactionEvent` MUST share the same currency. Cross-currency conversion inside the ledger engine is out of scope for MVP.

---

## 5. Epic 2 Integration Blueprint

During Epic 2:
1. **Balance Read**: `PhysicalAccountService` issues Query 1 for Owners/Co-Owners and Query 2 for Allocators.
2. **Reconciliation True-Up**: `POST /physical-accounts/{id}/reconcile` computes `drift = submitted_balance - current_balance`. If non-zero, it inserts a `TransactionEvent` and a single `LedgerEntry` linking `physical_account_id`, the owner's `Unallocated` virtual account, `owner_user_id`, and `amount = drift`.
3. **Concurrency Control**: Physical account reconciliations must execute under `SELECT ... FOR UPDATE` on the `physical_account` record to prevent concurrent true-up race conditions.
