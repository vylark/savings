"""Unit tests for ReconciliationService business logic and deficit tracking."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import AccountRole, Currency, TaxBand, TaxWrapper
from src.models.ledger import LedgerEntry, TransactionEvent
from src.models.physical_account import (
    Institution,
    PhysicalAccount,
    PhysicalAccountShare,
    ReconciliationEvent,
)
from src.models.user import User
from src.services.physical_account import PhysicalAccountService
from src.services.reconciliation import ReconciliationService


async def _make_user(db_session: AsyncSession, email: str, is_verified: bool = True) -> User:
    """Helper to create a User in the test database.

    Args:
        db_session: Active asynchronous database session.
        email: Email address for the user.
        is_verified: Verification status flag.

    Returns:
        Persisted User entity.
    """
    user = User(
        email=email,
        hashed_password="hashed_password",
        first_name="Test",
        last_name="Member",
        tax_band=TaxBand.BASIC,
        is_active=True,
        is_verified=is_verified,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_account(
    db_session: AsyncSession,
    owner: User,
    currency: Currency = Currency.GBP,
) -> PhysicalAccount:
    """Helper to create an Institution, PhysicalAccount, and OWNER share.

    Args:
        db_session: Active asynchronous database session.
        owner: User entity who owns the account.
        currency: Account base currency.

    Returns:
        Persisted PhysicalAccount entity.
    """
    inst = Institution(name=f"Inst-{uuid.uuid4().hex[:8]}")
    db_session.add(inst)
    await db_session.flush()

    account = PhysicalAccount(
        name="Test Savings Account",
        institution_id=inst.id,
        tax_wrapper=TaxWrapper.ISA,
        currency=currency,
    )
    db_session.add(account)
    await db_session.flush()

    share = PhysicalAccountShare(
        user_id=owner.id,
        physical_account_id=account.id,
        role=AccountRole.OWNER,
    )
    db_session.add(share)
    await db_session.flush()
    return account


async def _add_ledger_entry(
    db_session: AsyncSession,
    account: PhysicalAccount,
    user: User,
    amount: Decimal,
    virtual_account_id: uuid.UUID | None = None,
    description: str = "Deposit",
) -> LedgerEntry:
    """Helper to create a TransactionEvent and LedgerEntry.

    Args:
        db_session: Active asynchronous database session.
        account: Target PhysicalAccount.
        user: Owning/allocating user.
        amount: Signed entry amount.
        virtual_account_id: Target virtual bucket UUID; defaults to a new random UUID.
        description: Audit description for the transaction event.

    Returns:
        Persisted LedgerEntry entity.
    """
    tx = TransactionEvent(description=description)
    db_session.add(tx)
    await db_session.flush()

    v_id = virtual_account_id or uuid.uuid4()
    entry = LedgerEntry(
        transaction_id=tx.id,
        physical_account_id=account.id,
        virtual_account_id=v_id,
        user_id=user.id,
        currency=account.currency,
        amount=amount,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


@pytest.mark.asyncio
async def test_reconcile_account_positive_drift(db_session: AsyncSession) -> None:
    """Verify positive drift logs true-up entry to unallocated bucket without deficit warning."""
    owner = await _make_user(db_session, "owner.pos@example.com")
    account = await _make_account(db_session, owner=owner)

    # Seed initial balance: £1,000.00
    await _add_ledger_entry(db_session, account, owner, Decimal("1000.00"))

    # User submits £1,050.00 -> drift = +£50.00
    response = await ReconciliationService.reconcile_account(
        db=db_session,
        account=account,
        actor_user_id=owner.id,
        submitted_balance=Decimal("1050.00"),
        notes="Accrued interest true-up",
    )

    assert response.physical_account_id == account.id
    assert response.previous_balance == Decimal("1000.00")
    assert response.submitted_balance == Decimal("1050.00")
    assert response.calculated_drift == Decimal("50.00")
    assert response.transaction_id is not None
    assert response.deficit_warning is False
    assert response.reconciliation_event_id is not None

    # Verify ReconciliationEvent row
    event = await db_session.get(ReconciliationEvent, response.reconciliation_event_id)
    assert event is not None
    assert event.physical_account_id == account.id
    assert event.user_id == owner.id
    assert event.submitted_balance == Decimal("1050.00")
    assert event.calculated_drift == Decimal("50.00")

    # Verify TransactionEvent description
    tx_event = await db_session.get(TransactionEvent, response.transaction_id)
    assert tx_event is not None
    assert tx_event.description == "Accrued interest true-up"

    # Verify LedgerEntry true-up
    entries = (
        (await db_session.execute(select(LedgerEntry).where(LedgerEntry.transaction_id == response.transaction_id)))
        .scalars()
        .all()
    )
    assert len(entries) == 1
    true_up = entries[0]
    expected_bucket = await PhysicalAccountService.ensure_unallocated_bucket(db_session, owner.id, account.currency)
    assert true_up.physical_account_id == account.id
    assert true_up.user_id == owner.id
    assert true_up.virtual_account_id == expected_bucket
    assert true_up.amount == Decimal("50.00")
    assert true_up.currency == account.currency


@pytest.mark.asyncio
async def test_reconcile_account_negative_drift_with_deficit(db_session: AsyncSession) -> None:
    """Verify negative drift driving unallocated bucket below zero sets deficit_warning=True."""
    owner = await _make_user(db_session, "owner.neg@example.com")
    account = await _make_account(db_session, owner=owner)

    # Seed initial balance in a specific goal bucket (unallocated bucket has £0.00)
    goal_bucket = uuid.uuid4()
    await _add_ledger_entry(db_session, account, owner, Decimal("500.00"), virtual_account_id=goal_bucket)

    # User submits £480.00 -> drift = -£20.00. Unallocated becomes -£20.00 -> deficit!
    response = await ReconciliationService.reconcile_account(
        db=db_session,
        account=account,
        actor_user_id=owner.id,
        submitted_balance=Decimal("480.00"),
        notes=None,  # Should generate default description
    )

    assert response.previous_balance == Decimal("500.00")
    assert response.submitted_balance == Decimal("480.00")
    assert response.calculated_drift == Decimal("-20.00")
    assert response.transaction_id is not None
    assert response.deficit_warning is True

    # Check default description
    tx_event = await db_session.get(TransactionEvent, response.transaction_id)
    assert tx_event is not None
    assert tx_event.description == f"Reconciliation true-up for {account.name}"


@pytest.mark.asyncio
async def test_reconcile_account_negative_drift_without_deficit(db_session: AsyncSession) -> None:
    """Verify negative drift does not set deficit_warning when unallocated bucket remains >= 0."""
    owner = await _make_user(db_session, "owner.absorb@example.com")
    account = await _make_account(db_session, owner=owner)

    unallocated_bucket = await PhysicalAccountService.ensure_unallocated_bucket(db_session, owner.id, account.currency)
    # Seed £500.00 into account, with £100.00 in unallocated bucket
    await _add_ledger_entry(db_session, account, owner, Decimal("100.00"), virtual_account_id=unallocated_bucket)
    await _add_ledger_entry(db_session, account, owner, Decimal("400.00"), virtual_account_id=uuid.uuid4())

    # Drift is -£20.00; Unallocated drops from £100.00 to £80.00 >= 0
    response = await ReconciliationService.reconcile_account(
        db=db_session,
        account=account,
        actor_user_id=owner.id,
        submitted_balance=Decimal("480.00"),
    )

    assert response.calculated_drift == Decimal("-20.00")
    assert response.deficit_warning is False


@pytest.mark.asyncio
async def test_reconcile_account_zero_drift(db_session: AsyncSession) -> None:
    """Verify zero drift creates an audit event but no transaction or ledger entries."""
    owner = await _make_user(db_session, "owner.zero@example.com")
    account = await _make_account(db_session, owner=owner)

    await _add_ledger_entry(db_session, account, owner, Decimal("2000.00"))

    # Initial counts
    tx_count_before = (await db_session.execute(select(TransactionEvent))).scalars().all()
    ledger_count_before = (await db_session.execute(select(LedgerEntry))).scalars().all()

    response = await ReconciliationService.reconcile_account(
        db=db_session,
        account=account,
        actor_user_id=owner.id,
        submitted_balance=Decimal("2000.00"),
    )

    assert response.previous_balance == Decimal("2000.00")
    assert response.submitted_balance == Decimal("2000.00")
    assert response.calculated_drift == Decimal("0.00")
    assert response.transaction_id is None
    assert response.deficit_warning is False

    # Reconciliation event must still be logged
    event = await db_session.get(ReconciliationEvent, response.reconciliation_event_id)
    assert event is not None
    assert event.calculated_drift == Decimal("0.00")

    # No additional transactions or entries should be created
    tx_count_after = (await db_session.execute(select(TransactionEvent))).scalars().all()
    ledger_count_after = (await db_session.execute(select(LedgerEntry))).scalars().all()
    assert len(tx_count_after) == len(tx_count_before)
    assert len(ledger_count_after) == len(ledger_count_before)


@pytest.mark.asyncio
async def test_reconcile_account_co_owner_actor(db_session: AsyncSession) -> None:
    """Verify CO_OWNER can trigger reconciliation with true-up allocated to the primary OWNER."""
    owner = await _make_user(db_session, "primary.owner@example.com")
    co_owner = await _make_user(db_session, "co.owner@example.com")
    account = await _make_account(db_session, owner=owner)

    # Add CO_OWNER share
    db_session.add(
        PhysicalAccountShare(
            user_id=co_owner.id,
            physical_account_id=account.id,
            role=AccountRole.CO_OWNER,
        )
    )
    await db_session.flush()

    await _add_ledger_entry(db_session, account, owner, Decimal("1000.00"))

    # Co-owner submits balance
    response = await ReconciliationService.reconcile_account(
        db=db_session,
        account=account,
        actor_user_id=co_owner.id,
        submitted_balance=Decimal("1100.00"),
    )

    assert response.calculated_drift == Decimal("100.00")

    # Audit event records the co-owner actor
    event = await db_session.get(ReconciliationEvent, response.reconciliation_event_id)
    assert event is not None
    assert event.user_id == co_owner.id

    # Ledger entry true-up belongs to the primary OWNER
    entry = (
        (await db_session.execute(select(LedgerEntry).where(LedgerEntry.transaction_id == response.transaction_id)))
        .scalars()
        .one()
    )
    owner_bucket = await PhysicalAccountService.ensure_unallocated_bucket(db_session, owner.id, account.currency)
    assert entry.user_id == owner.id
    assert entry.virtual_account_id == owner_bucket
    assert entry.amount == Decimal("100.00")
