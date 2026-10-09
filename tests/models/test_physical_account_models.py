"""Database model integrity, constraint, and seeding tests for Physical Accounts and Ledger."""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import AccountRole, Currency, TaxBand, TaxWrapper
from src.db.seed import INITIAL_INSTITUTIONS, SeedError, seed_development_data, seed_institutions
from src.models.ledger import LedgerEntry, TransactionEvent
from src.models.physical_account import (
    Institution,
    PhysicalAccount,
    PhysicalAccountShare,
    ReconciliationEvent,
)
from src.models.user import User


async def _create_test_user(db_session: AsyncSession, email: str = "model.user@example.com") -> User:
    """Helper to insert and flush a test User entity."""
    user = User(
        email=email,
        hashed_password="hashed_password_placeholder",
        first_name="Test",
        last_name="User",
        tax_band=TaxBand.BASIC,
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _create_test_institution(
    db_session: AsyncSession,
    name: str = "Barclays",
) -> Institution:
    """Helper to insert and flush a test Institution entity."""
    inst = Institution(name=name)
    db_session.add(inst)
    await db_session.flush()
    return inst


async def test_institution_hierarchy_and_uniqueness(db_session: AsyncSession) -> None:
    """Verify Institution creation, self-referential parent link, and unique name constraint."""
    parent = Institution(name="Lloyds Bank")
    db_session.add(parent)
    await db_session.flush()

    child = Institution(
        name="Scottish Widows",
        parent_institution_id=parent.id,
    )
    db_session.add(child)
    await db_session.flush()

    assert child.parent_institution_id == parent.id

    # Duplicate name should trigger IntegrityError
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            duplicate = Institution(name="Lloyds Bank")
            db_session.add(duplicate)
            await db_session.flush()


async def test_physical_account_foreign_key_and_restrict_delete(db_session: AsyncSession) -> None:
    """Verify PhysicalAccount institution FK enforcement and RESTRICT on institution deletion."""
    # 1. Invalid institution_id triggers ForeignKeyViolation
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            invalid_account = PhysicalAccount(
                name="Orphan Saver",
                institution_id=uuid.uuid4(),
                tax_wrapper=TaxWrapper.NONE,
                currency=Currency.GBP,
            )
            db_session.add(invalid_account)
            await db_session.flush()

    # 2. Deleting an Institution linked to a PhysicalAccount is restricted
    inst = await _create_test_institution(db_session)
    account = PhysicalAccount(
        name="Fixed Rate Bond",
        institution_id=inst.id,
        tax_wrapper=TaxWrapper.ISA,
        currency=Currency.GBP,
        interest_rate=Decimal("0.0475"),
        access_delay_days=0,
        maturity_date=date(2027, 9, 30),
    )
    db_session.add(account)
    await db_session.flush()
    assert account.maturity_date == date(2027, 9, 30)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.delete(inst)
            await db_session.flush()


async def test_physical_account_check_constraints(db_session: AsyncSession) -> None:
    """Verify CheckConstraints on negative access_delay_days and negative interest_rate."""
    inst = await _create_test_institution(db_session)

    # Negative access_delay_days
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            neg_delay_account = PhysicalAccount(
                name="Negative Delay",
                institution_id=inst.id,
                tax_wrapper=TaxWrapper.NONE,
                currency=Currency.GBP,
                access_delay_days=-1,
            )
            db_session.add(neg_delay_account)
            await db_session.flush()

    # Negative interest_rate
    inst2 = await _create_test_institution(db_session, name="Monzo")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            neg_rate_account = PhysicalAccount(
                name="Negative Rate",
                institution_id=inst2.id,
                tax_wrapper=TaxWrapper.NONE,
                currency=Currency.GBP,
                interest_rate=Decimal("-0.0100"),
            )
            db_session.add(neg_rate_account)
            await db_session.flush()


async def test_physical_account_share_uniqueness_and_cascade(db_session: AsyncSession) -> None:
    """Verify unique (user_id, physical_account_id) constraint and cascade delete on PhysicalAccount."""
    user = await _create_test_user(db_session)
    inst = await _create_test_institution(db_session)
    account = PhysicalAccount(
        name="Everyday Saver",
        institution_id=inst.id,
        tax_wrapper=TaxWrapper.NONE,
        currency=Currency.GBP,
    )
    db_session.add(account)
    await db_session.flush()

    share1 = PhysicalAccountShare(
        user_id=user.id,
        physical_account_id=account.id,
        role=AccountRole.OWNER,
    )
    db_session.add(share1)
    await db_session.flush()

    # Duplicate share for same (user_id, physical_account_id) triggers IntegrityError
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            share_dup = PhysicalAccountShare(
                user_id=user.id,
                physical_account_id=account.id,
                role=AccountRole.CO_OWNER,
            )
            db_session.add(share_dup)
            await db_session.flush()

    # Re-create and verify cascade deletion when PhysicalAccount is deleted
    user2 = await _create_test_user(db_session, email="cascade@example.com")
    inst2 = await _create_test_institution(db_session, name="Vanguard")
    acc2 = PhysicalAccount(
        name="S&S ISA",
        institution_id=inst2.id,
        tax_wrapper=TaxWrapper.ISA,
        currency=Currency.GBP,
    )
    db_session.add(acc2)
    await db_session.flush()

    share2 = PhysicalAccountShare(
        user_id=user2.id,
        physical_account_id=acc2.id,
        role=AccountRole.OWNER,
    )
    db_session.add(share2)
    await db_session.flush()

    await db_session.delete(acc2)
    await db_session.flush()

    remaining = (
        (
            await db_session.execute(
                select(PhysicalAccountShare).where(PhysicalAccountShare.physical_account_id == acc2.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


async def test_reconciliation_and_ledger_audit_preservation(db_session: AsyncSession) -> None:
    """Verify ReconciliationEvent and LedgerEntry creation and RESTRICT on User deletion."""
    user = await _create_test_user(db_session, email="auditor@example.com")
    inst = await _create_test_institution(db_session)
    account = PhysicalAccount(
        name="Audit Account",
        institution_id=inst.id,
        tax_wrapper=TaxWrapper.GIA,
        currency=Currency.GBP,
    )
    db_session.add(account)
    await db_session.flush()

    recon = ReconciliationEvent(
        physical_account_id=account.id,
        user_id=user.id,
        submitted_balance=Decimal("1000.00"),
        calculated_drift=Decimal("1000.00"),
    )
    tx_event = TransactionEvent(description="Initial true-up")
    db_session.add_all([recon, tx_event])
    await db_session.flush()

    entry = LedgerEntry(
        transaction_id=tx_event.id,
        physical_account_id=account.id,
        virtual_account_id=uuid.uuid4(),
        user_id=user.id,
        currency=Currency.GBP,
        amount=Decimal("1000.00"),
    )
    db_session.add(entry)
    await db_session.flush()

    # Attempting to delete a User who has reconciliation/ledger records is blocked by RESTRICT
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.delete(user)
            await db_session.flush()


async def test_seed_institutions_idempotency(db_session: AsyncSession) -> None:
    """Verify seed_institutions populates all initial providers and is idempotent on repeat calls."""
    first_run = await seed_institutions(db_session)
    assert len(first_run) == len(INITIAL_INSTITUTIONS)

    # Check parent-child links for First Direct -> HSBC UK and Scottish Widows -> Lloyds Bank
    by_name = {inst.name: inst for inst in first_run}
    assert "Scottish Widows" in by_name
    assert "Lloyds Bank" in by_name
    assert by_name["Scottish Widows"].parent_institution_id == by_name["Lloyds Bank"].id
    assert by_name["First Direct"].parent_institution_id == by_name["HSBC UK"].id

    # Second run should not duplicate rows
    second_run = await seed_institutions(db_session)
    assert len(second_run) == len(INITIAL_INSTITUTIONS)


async def test_seed_development_data_success_and_error(db_session: AsyncSession) -> None:
    """Verify seed_development_data runs cleanly and raises SeedError on database failure."""

    class _DummySessionCtx:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *args: object) -> None:
            pass

    with patch("src.db.seed.create_session", return_value=_DummySessionCtx()):
        await seed_development_data()

    # Also test when a user exists in the database
    await _create_test_user(db_session, email="seeded.admin@example.com")
    with patch("src.db.seed.create_session", return_value=_DummySessionCtx()):
        await seed_development_data()

    # Test failure branch raising SeedError
    broken_session = AsyncMock(spec=AsyncSession)
    broken_session.execute.side_effect = RuntimeError("DB failure")

    class _BrokenSessionCtx:
        async def __aenter__(self) -> AsyncSession:
            return broken_session

        async def __aexit__(self, *args: object) -> None:
            pass

    with (
        patch("src.db.seed.create_session", return_value=_BrokenSessionCtx()),
        pytest.raises(SeedError, match="Failed to complete database seeding step"),
    ):
        await seed_development_data()
