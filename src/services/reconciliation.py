"""Service module handling balance reconciliation, drift true-up, and deficit tracking."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import AccountRole, Currency
from src.models.ledger import LedgerEntry, TransactionEvent
from src.models.physical_account import PhysicalAccount, PhysicalAccountShare, ReconciliationEvent
from src.schemas.physical_account import ReconciliationResponse
from src.services.physical_account import PhysicalAccountService


class ReconciliationService:
    """Manages physical account reconciliation, row-level locking, and true-up ledger operations."""

    @staticmethod
    async def _resolve_primary_owner(
        db: AsyncSession,
        account_id: uuid.UUID,
        fallback_user_id: uuid.UUID,
    ) -> uuid.UUID:
        """Resolves the primary owner UUID of a physical account for unallocated attribution.

        Args:
            db: Active asynchronous database session.
            account_id: Target physical account UUID.
            fallback_user_id: User UUID to use if no explicit OWNER share is found.

        Returns:
            UUID of the resolved owner user.
        """
        owner_stmt = select(PhysicalAccountShare.user_id).where(
            PhysicalAccountShare.physical_account_id == account_id,
            PhysicalAccountShare.role == AccountRole.OWNER,
        )
        owner_id = (await db.execute(owner_stmt)).scalar_one_or_none()
        return owner_id or fallback_user_id

    @staticmethod
    async def _get_current_ledger_balance(
        db: AsyncSession,
        account_id: uuid.UUID,
        currency: Currency,
    ) -> Decimal:
        """Calculates current total balance from ledger entries matching the designated base currency.

        Args:
            db: Active asynchronous database session.
            account_id: Target physical account UUID.
            currency: Base currency denomination to match.

        Returns:
            Calculated ledger balance as Decimal.
        """
        bal_stmt = select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00"))).where(
            LedgerEntry.physical_account_id == account_id,
            LedgerEntry.currency == currency,
        )
        return (await db.execute(bal_stmt)).scalar_one()

    @staticmethod
    async def _apply_true_up(
        db: AsyncSession,
        account: PhysicalAccount,
        owner_id: uuid.UUID,
        drift: Decimal,
        notes: str | None = None,
    ) -> tuple[uuid.UUID, bool]:
        """Creates true-up TransactionEvent and LedgerEntry and checks deficit condition.

        Args:
            db: Active asynchronous database session.
            account: Locked PhysicalAccount entity being reconciled.
            owner_id: Primary owner UUID whose Unallocated bucket receives the true-up.
            drift: Monetary drift amount to record (positive or negative).
            notes: Optional user-supplied audit note describing the true-up.

        Returns:
            Tuple of (transaction_id, deficit_warning).
        """
        unallocated_virtual_id = await PhysicalAccountService.ensure_unallocated_bucket(
            db=db,
            user_id=owner_id,
            currency=account.currency,
        )

        # Check owner's unallocated balance to evaluate deficit state
        unallocated_bal_stmt = select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00"))).where(
            LedgerEntry.user_id == owner_id,
            LedgerEntry.virtual_account_id == unallocated_virtual_id,
            LedgerEntry.currency == account.currency,
        )
        pre_unallocated_bal = (await db.execute(unallocated_bal_stmt)).scalar_one()
        deficit_warning = (pre_unallocated_bal + drift) < Decimal("0.00")

        clean_notes = notes.strip() if notes and notes.strip() else None
        tx_desc = clean_notes or f"Reconciliation true-up for {account.name}"
        tx_event = TransactionEvent(description=tx_desc)
        db.add(tx_event)
        await db.flush()

        entry = LedgerEntry(
            transaction_id=tx_event.id,
            physical_account_id=account.id,
            virtual_account_id=unallocated_virtual_id,
            user_id=owner_id,
            currency=account.currency,
            amount=drift,
        )
        db.add(entry)

        return tx_event.id, deficit_warning

    @staticmethod
    async def _record_reconciliation_event(
        db: AsyncSession,
        account_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        submitted_balance: Decimal,
        calculated_drift: Decimal,
    ) -> ReconciliationEvent:
        """Records and commits an immutable ReconciliationEvent audit row.

        Args:
            db: Active asynchronous database session.
            account_id: Target physical account UUID.
            actor_user_id: User UUID of the actor who submitted the reconciliation.
            submitted_balance: Bank statement balance submitted by user.
            calculated_drift: Computed drift difference.

        Returns:
            Refreshed ReconciliationEvent entity with database-assigned timestamp.
        """
        event = ReconciliationEvent(
            physical_account_id=account_id,
            user_id=actor_user_id,
            submitted_balance=submitted_balance,
            calculated_drift=calculated_drift,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    @staticmethod
    async def reconcile_account(
        db: AsyncSession,
        account: PhysicalAccount,
        actor_user_id: uuid.UUID,
        submitted_balance: Decimal,
        notes: str | None = None,
    ) -> ReconciliationResponse:
        """Executes atomic reconciliation and logs true-up transactions for any drift.

        Locks the physical account row to prevent concurrent race conditions, identifies
        the primary owner to attribute the unallocated bucket, calculates drift between
        submitted statement balance and ledger balance, logs an immutable ReconciliationEvent,
        and creates a TransactionEvent and LedgerEntry when drift is non-zero.

        Args:
            db: Active asynchronous database session.
            account: PhysicalAccount entity to reconcile.
            actor_user_id: UUID of user triggering the reconciliation.
            submitted_balance: Real-world statement balance confirmed by user.
            notes: Optional audit note describing the true-up.

        Returns:
            ReconciliationResponse detailing previous balance, drift, transaction, and deficit warning.
        """
        # 1. Row-level lock on PhysicalAccount to prevent concurrent reconciliation races
        lock_stmt = select(PhysicalAccount).where(PhysicalAccount.id == account.id).with_for_update()
        locked_account = (await db.execute(lock_stmt)).scalar_one()

        # 2. Identify primary owner of the account
        owner_id = await ReconciliationService._resolve_primary_owner(
            db=db,
            account_id=locked_account.id,
            fallback_user_id=actor_user_id,
        )

        # 3. Calculate current balance from ledger matching account base currency
        current_balance = await ReconciliationService._get_current_ledger_balance(
            db=db,
            account_id=locked_account.id,
            currency=locked_account.currency,
        )
        drift = submitted_balance - current_balance

        # 4. Handle drift true-up if non-zero
        transaction_id: uuid.UUID | None = None
        deficit_warning = False
        if drift != Decimal("0.00"):
            transaction_id, deficit_warning = await ReconciliationService._apply_true_up(
                db=db,
                account=locked_account,
                owner_id=owner_id,
                drift=drift,
                notes=notes,
            )

        # 5. Record immutable ReconciliationEvent audit log
        event = await ReconciliationService._record_reconciliation_event(
            db=db,
            account_id=locked_account.id,
            actor_user_id=actor_user_id,
            submitted_balance=submitted_balance,
            calculated_drift=drift,
        )

        return ReconciliationResponse(
            reconciliation_event_id=event.id,
            physical_account_id=locked_account.id,
            previous_balance=current_balance,
            submitted_balance=submitted_balance,
            calculated_drift=drift,
            transaction_id=transaction_id,
            deficit_warning=deficit_warning,
            timestamp=event.timestamp,
        )
