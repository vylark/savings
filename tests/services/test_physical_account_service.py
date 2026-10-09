"""Unit tests for PhysicalAccountService and AccountAccessChecker RBAC dependencies."""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.physical_account import (
    require_account_member,
    require_account_owner,
    require_account_reconciler,
)
from src.core.constants import AccountRole, Currency, TaxBand, TaxWrapper
from src.models.ledger import LedgerEntry, TransactionEvent
from src.models.physical_account import Institution, PhysicalAccount, PhysicalAccountShare
from src.models.user import User
from src.services.physical_account import PhysicalAccountService


async def _make_user(db_session: AsyncSession, email: str) -> User:
    """Helper to create a verified User in the test database."""
    user = User(
        email=email,
        hashed_password="hashed_password",
        first_name="Test",
        last_name="Member",
        tax_band=TaxBand.BASIC,
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_account(db_session: AsyncSession) -> PhysicalAccount:
    """Helper to create an Institution and PhysicalAccount in the test database."""
    inst = Institution(name=f"Inst-{uuid.uuid4().hex[:8]}")
    db_session.add(inst)
    await db_session.flush()

    account = PhysicalAccount(
        name="Shared Savings",
        institution_id=inst.id,
        tax_wrapper=TaxWrapper.NONE,
        currency=Currency.GBP,
    )
    db_session.add(account)
    await db_session.flush()
    return account


async def test_account_access_checker_rbac_tiers(db_session: AsyncSession) -> None:
    """Verify AccountAccessChecker enforces 404 for non-members and 403 for insufficient role tiers."""
    owner = await _make_user(db_session, "owner@example.com")
    co_owner = await _make_user(db_session, "coowner@example.com")
    allocator = await _make_user(db_session, "allocator@example.com")
    outsider = await _make_user(db_session, "outsider@example.com")
    account = await _make_account(db_session)

    db_session.add_all(
        [
            PhysicalAccountShare(user_id=owner.id, physical_account_id=account.id, role=AccountRole.OWNER),
            PhysicalAccountShare(user_id=co_owner.id, physical_account_id=account.id, role=AccountRole.CO_OWNER),
            PhysicalAccountShare(user_id=allocator.id, physical_account_id=account.id, role=AccountRole.ALLOCATOR),
        ]
    )
    await db_session.flush()

    # 1. Non-member receives 404 Not Found
    with pytest.raises(HTTPException) as exc_info:
        await require_account_member(account_id=account.id, current_user=outsider, db=db_session)
    assert exc_info.value.status_code == 404

    # 2. Non-existent account UUID receives 404 Not Found
    with pytest.raises(HTTPException) as exc_info:
        await require_account_member(account_id=uuid.uuid4(), current_user=owner, db=db_session)
    assert exc_info.value.status_code == 404

    # 3. Allocator passes require_account_member, fails require_account_reconciler and require_account_owner (403)
    resolved_acc, resolved_share = await require_account_member(
        account_id=account.id,
        current_user=allocator,
        db=db_session,
    )
    assert resolved_acc.id == account.id
    assert resolved_share.role == AccountRole.ALLOCATOR

    with pytest.raises(HTTPException) as exc_info:
        await require_account_reconciler(account_id=account.id, current_user=allocator, db=db_session)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await require_account_owner(account_id=account.id, current_user=allocator, db=db_session)
    assert exc_info.value.status_code == 403

    # 4. Co-Owner passes require_account_reconciler, fails require_account_owner (403)
    _, co_share = await require_account_reconciler(
        account_id=account.id,
        current_user=co_owner,
        db=db_session,
    )
    assert co_share.role == AccountRole.CO_OWNER

    with pytest.raises(HTTPException) as exc_info:
        await require_account_owner(account_id=account.id, current_user=co_owner, db=db_session)
    assert exc_info.value.status_code == 403

    # 5. Owner passes require_account_owner
    _, owner_share = await require_account_owner(
        account_id=account.id,
        current_user=owner,
        db=db_session,
    )
    assert owner_share.role == AccountRole.OWNER


async def test_get_account_balance_privacy_filter(db_session: AsyncSession) -> None:
    """Verify get_account_balance returns full sum for OWNER/CO_OWNER and user-only slice for ALLOCATOR."""
    user_a = await _make_user(db_session, "owner.balance@example.com")
    user_b = await _make_user(db_session, "allocator.balance@example.com")
    account = await _make_account(db_session)

    # Empty account balance is 0.00
    empty_bal = await PhysicalAccountService.get_account_balance(
        db=db_session,
        account_id=account.id,
        role=AccountRole.OWNER,
        user_id=user_a.id,
    )
    assert empty_bal == Decimal("0.00")

    # Insert £10,000 from Owner User A and £500 from Allocator User B
    tx = TransactionEvent(description="Shared allocation test")
    db_session.add(tx)
    await db_session.flush()

    db_session.add_all(
        [
            LedgerEntry(
                transaction_id=tx.id,
                physical_account_id=account.id,
                virtual_account_id=uuid.uuid4(),
                user_id=user_a.id,
                currency=Currency.GBP,
                amount=Decimal("10000.00"),
            ),
            LedgerEntry(
                transaction_id=tx.id,
                physical_account_id=account.id,
                virtual_account_id=uuid.uuid4(),
                user_id=user_b.id,
                currency=Currency.GBP,
                amount=Decimal("500.00"),
            ),
        ]
    )
    await db_session.flush()

    # Owner sees total £10,500.00
    owner_bal = await PhysicalAccountService.get_account_balance(
        db=db_session,
        account_id=account.id,
        role=AccountRole.OWNER,
        user_id=user_a.id,
    )
    assert owner_bal == Decimal("10500.00")

    # Co-Owner sees total £10,500.00
    co_owner_bal = await PhysicalAccountService.get_account_balance(
        db=db_session,
        account_id=account.id,
        role=AccountRole.CO_OWNER,
        user_id=user_b.id,
    )
    assert co_owner_bal == Decimal("10500.00")

    # Allocator User B strictly sees only their £500.00 slice
    allocator_bal = await PhysicalAccountService.get_account_balance(
        db=db_session,
        account_id=account.id,
        role=AccountRole.ALLOCATOR,
        user_id=user_b.id,
    )
    assert allocator_bal == Decimal("500.00")

    # Defense-in-depth: Insert an entry with mismatched currency (USD instead of GBP)
    db_session.add(
        LedgerEntry(
            transaction_id=tx.id,
            physical_account_id=account.id,
            virtual_account_id=uuid.uuid4(),
            user_id=user_a.id,
            currency=Currency.USD,
            amount=Decimal("9999.00"),
        )
    )
    await db_session.flush()

    # Owner balance still strictly reflects only matching GBP entries (£10,500.00)
    owner_bal_after_mismatch = await PhysicalAccountService.get_account_balance(
        db=db_session,
        account_id=account.id,
        role=AccountRole.OWNER,
        user_id=user_a.id,
    )
    assert owner_bal_after_mismatch == Decimal("10500.00")


async def test_ensure_unallocated_bucket_deterministic_uuid(db_session: AsyncSession) -> None:
    """Verify ensure_unallocated_bucket generates deterministic per-user, per-currency UUIDs."""
    user_id = uuid.uuid4()
    gbp_bucket_1 = await PhysicalAccountService.ensure_unallocated_bucket(db_session, user_id, Currency.GBP)
    gbp_bucket_2 = await PhysicalAccountService.ensure_unallocated_bucket(db_session, user_id, Currency.GBP)
    usd_bucket = await PhysicalAccountService.ensure_unallocated_bucket(db_session, user_id, Currency.USD)

    assert gbp_bucket_1 == gbp_bucket_2
    assert gbp_bucket_1 != usd_bucket


async def test_service_list_institutions_and_create_account(db_session: AsyncSession) -> None:
    """Verify PhysicalAccountService.list_institutions and create_account directly."""
    from src.schemas.physical_account import PhysicalAccountCreate

    user = await _make_user(db_session, "service.creator@example.com")
    other_user = await _make_user(db_session, "service.other@example.com")
    inst = Institution(name="Service Test Bank")
    db_session.add(inst)
    await db_session.flush()

    all_insts = await PhysicalAccountService.list_institutions(db=db_session)
    assert any(i.id == inst.id for i in all_insts)

    filtered_insts = await PhysicalAccountService.list_institutions(db=db_session, search="Service Test")
    assert len(filtered_insts) == 1
    assert filtered_insts[0].id == inst.id

    payload = PhysicalAccountCreate(
        name="Direct Service Account",
        institution_id=inst.id,
        tax_wrapper="ISA",
        currency="GBP",
        interest_rate=Decimal("0.0425"),
        access_delay_days=0,
    )
    created = await PhysicalAccountService.create_account(
        db=db_session,
        user=user,
        data=payload,
        owner_id=other_user.id,
    )
    assert created.name == "Direct Service Account"
    assert created.institution.id == inst.id

    # Verify unallocated bucket for the owner was deterministically initialized
    expected_bucket = await PhysicalAccountService.ensure_unallocated_bucket(
        db_session, other_user.id, Currency(created.currency)
    )
    assert expected_bucket == uuid.uuid5(other_user.id, f"unallocated_{created.currency.value}")

    # Missing institution raises 404
    bad_inst_payload = PhysicalAccountCreate(
        name="Missing Inst",
        institution_id=uuid.uuid4(),
        tax_wrapper="NONE",
    )
    with pytest.raises(HTTPException) as exc_info:
        await PhysicalAccountService.create_account(db=db_session, user=user, data=bad_inst_payload)
    assert exc_info.value.status_code == 404

    # Missing custom owner_id raises 404
    with pytest.raises(HTTPException) as exc_info:
        await PhysicalAccountService.create_account(
            db=db_session,
            user=user,
            data=payload,
            owner_id=uuid.uuid4(),
        )
    assert exc_info.value.status_code == 404
