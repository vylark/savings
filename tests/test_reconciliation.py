"""Integration tests for Physical Account reconciliation and deficit handling (Story 2.4)."""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import AccountRole, Currency, TaxBand, TaxWrapper
from src.core.mail import outbox
from src.main import app
from src.models.ledger import LedgerEntry, TransactionEvent
from src.models.physical_account import (
    Institution,
    PhysicalAccount,
    PhysicalAccountShare,
    ReconciliationEvent,
)
from src.models.user import User


async def _verify_authenticated_client(client: httpx.AsyncClient, email: str = "user@example.com") -> None:
    """Helper to verify the user account associated with an authenticated test client.

    Args:
        client: Authenticated HTTPX client.
        email: Registered user email to verify.
    """
    req_res = await client.post("/auth/request-verify-token", json={"email": email})
    assert req_res.status_code == 202
    token = outbox[-1]["body"].split("token is: ")[-1].strip()
    verify_res = await client.post("/auth/verify", json={"token": token})
    assert verify_res.status_code == 200


async def _create_authenticated_user_client(
    email: str = "collaborator@example.com",
    password: str = "SavingsPlatform2026!XyZ#9",
    first_name: str = "Collab",
    last_name: str = "User",
    tax_band: TaxBand = TaxBand.BASIC,
) -> httpx.AsyncClient:
    """Helper to register, verify, and authenticate a distinct test user client.

    Args:
        email: User email.
        password: User password.
        first_name: Given name.
        last_name: Surname.
        tax_band: UK income tax band.

    Returns:
        Configured and authenticated HTTPX client with Bearer token.
    """
    transport = httpx.ASGITransport(app=app)
    authed_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    reg_res = await authed_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
            "tax_band": tax_band.value,
        },
    )
    assert reg_res.status_code == 201

    login_res = await authed_client.post(
        "/auth/jwt/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_res.status_code == 200
    access_token = login_res.json()["access_token"]
    authed_client.headers["Authorization"] = f"Bearer {access_token}"

    await _verify_authenticated_client(authed_client, email=email)
    return authed_client


async def _seed_account_with_balance(
    db_session: AsyncSession,
    owner_email: str,
    amount: Decimal,
) -> PhysicalAccount:
    """Helper to create a physical account with an initial ledger balance.

    Args:
        db_session: Active database session.
        owner_email: Email of the owner user.
        amount: Initial ledger balance.

    Returns:
        Created PhysicalAccount entity.
    """
    owner = (await db_session.execute(select(User).where(User.__table__.c.email == owner_email))).scalar_one()
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    account = PhysicalAccount(
        name="Reconciliation Account",
        institution_id=barclays.id,
        tax_wrapper=TaxWrapper.ISA,
        currency=Currency.GBP,
    )
    db_session.add(account)
    await db_session.flush()

    db_session.add(
        PhysicalAccountShare(
            user_id=owner.id,
            physical_account_id=account.id,
            role=AccountRole.OWNER,
        )
    )
    await db_session.flush()

    if amount != Decimal("0.00"):
        tx = TransactionEvent(description="Initial Opening Deposit")
        db_session.add(tx)
        await db_session.flush()

        db_session.add(
            LedgerEntry(
                transaction_id=tx.id,
                physical_account_id=account.id,
                virtual_account_id=uuid.uuid4(),
                user_id=owner.id,
                currency=account.currency,
                amount=amount,
            )
        )
        await db_session.flush()

    await db_session.commit()
    return account


@pytest.mark.asyncio
async def test_reconcile_physical_account_owner_positive_drift(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC1: Positive drift true-up increases ledger balance and creates audit log."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("1000.00"))

    payload = {
        "submitted_balance": "1050.00",
        "notes": "Accrued interest statement",
    }
    res = await authenticated_client.post(f"/physical-accounts/{account.id}/reconcile", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["physical_account_id"] == str(account.id)
    assert data["previous_balance"] == "1000.00"
    assert data["submitted_balance"] == "1050.00"
    assert data["calculated_drift"] == "50.00"
    assert data["transaction_id"] is not None
    assert data["deficit_warning"] is False
    assert data["reconciliation_event_id"] is not None
    assert "timestamp" in data

    # Verify updated ledger balance on GET /physical-accounts/{id}
    get_res = await authenticated_client.get(f"/physical-accounts/{account.id}")
    assert get_res.status_code == 200
    assert get_res.json()["balance"] == "1050.00"


@pytest.mark.asyncio
async def test_reconcile_physical_account_negative_drift_deficit(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC2: Negative drift driving unallocated bucket below 0 sets deficit_warning=True."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("500.00"))

    payload = {
        "submitted_balance": "480.00",
        "notes": "Monthly management charge",
    }
    res = await authenticated_client.post(f"/physical-accounts/{account.id}/reconcile", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["previous_balance"] == "500.00"
    assert data["submitted_balance"] == "480.00"
    assert data["calculated_drift"] == "-20.00"
    assert data["transaction_id"] is not None
    assert data["deficit_warning"] is True

    # Account total balance in GET /physical-accounts/{id} matches the submitted £480.00
    get_res = await authenticated_client.get(f"/physical-accounts/{account.id}")
    assert get_res.status_code == 200
    assert get_res.json()["balance"] == "480.00"


@pytest.mark.asyncio
async def test_reconcile_physical_account_zero_drift(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC3: Zero drift logs ReconciliationEvent but creates no transaction or entries."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("2000.00"))

    payload = {
        "submitted_balance": "2000.00",
    }
    res = await authenticated_client.post(f"/physical-accounts/{account.id}/reconcile", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["previous_balance"] == "2000.00"
    assert data["submitted_balance"] == "2000.00"
    assert data["calculated_drift"] == "0.00"
    assert data["transaction_id"] is None
    assert data["deficit_warning"] is False

    # Reconciliation event was logged in DB
    event_id = uuid.UUID(data["reconciliation_event_id"])
    event = await db_session.get(ReconciliationEvent, event_id)
    assert event is not None
    assert event.calculated_drift == Decimal("0.00")


@pytest.mark.asyncio
async def test_reconcile_physical_account_co_owner_success(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify CO_OWNER can reconcile account; true-up ledger entry belongs to primary owner."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("1000.00"))

    co_owner_client = await _create_authenticated_user_client(email="coowner.recon@example.com")
    co_owner_user = (
        (await db_session.execute(select(User).where(User.__table__.c.email == "coowner.recon@example.com")))
        .scalars()
        .one()
    )

    # Grant CO_OWNER role
    share_res = await authenticated_client.post(
        f"/physical-accounts/{account.id}/shares",
        json={"email": "coowner.recon@example.com", "role": "CO_OWNER"},
    )
    assert share_res.status_code == 201

    # CO_OWNER submits reconciliation
    recon_res = await co_owner_client.post(
        f"/physical-accounts/{account.id}/reconcile",
        json={"submitted_balance": "1100.00"},
    )
    assert recon_res.status_code == 200
    recon_data = recon_res.json()
    assert recon_data["calculated_drift"] == "100.00"

    # Verify audit event actor is CO_OWNER
    event = await db_session.get(ReconciliationEvent, uuid.UUID(recon_data["reconciliation_event_id"]))
    assert event is not None
    assert event.user_id == co_owner_user.id

    # Verify ledger entry belongs to primary owner
    entry = (
        (
            await db_session.execute(
                select(LedgerEntry).where(LedgerEntry.transaction_id == uuid.UUID(recon_data["transaction_id"]))
            )
        )
        .scalars()
        .one()
    )
    owner_user = (
        await db_session.execute(select(User).where(User.__table__.c.email == "user@example.com"))
    ).scalar_one()
    assert entry.user_id == owner_user.id

    await co_owner_client.aclose()


@pytest.mark.asyncio
async def test_reconcile_physical_account_allocator_forbidden(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC4: ALLOCATOR role cannot reconcile and receives 403 Forbidden."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("1000.00"))

    allocator_client = await _create_authenticated_user_client(email="allocator.recon@example.com")

    # Grant ALLOCATOR role
    share_res = await authenticated_client.post(
        f"/physical-accounts/{account.id}/shares",
        json={"email": "allocator.recon@example.com", "role": "ALLOCATOR"},
    )
    assert share_res.status_code == 201

    # ALLOCATOR attempts to reconcile
    res = await allocator_client.post(
        f"/physical-accounts/{account.id}/reconcile",
        json={"submitted_balance": "1000.00"},
    )
    assert res.status_code == 403
    assert "Operation requires" in res.json()["detail"]

    await allocator_client.aclose()


@pytest.mark.asyncio
async def test_reconcile_physical_account_outsider_not_found(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify unshared non-member receives 404 Not Found."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("1000.00"))

    outsider_client = await _create_authenticated_user_client(email="outsider.recon@example.com")

    res = await outsider_client.post(
        f"/physical-accounts/{account.id}/reconcile",
        json={"submitted_balance": "1000.00"},
    )
    assert res.status_code == 404
    assert "not found or access denied" in res.json()["detail"]

    await outsider_client.aclose()


@pytest.mark.asyncio
async def test_reconcile_physical_account_validation_errors(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify 422 Unprocessable Entity on invalid request payloads."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("1000.00"))

    # Invalid decimal places (3 decimal places)
    res_dec = await authenticated_client.post(
        f"/physical-accounts/{account.id}/reconcile",
        json={"submitted_balance": "1000.123"},
    )
    assert res_dec.status_code == 422

    # Excessively long notes (>255 chars)
    res_notes = await authenticated_client.post(
        f"/physical-accounts/{account.id}/reconcile",
        json={"submitted_balance": "1000.00", "notes": "X" * 256},
    )
    assert res_notes.status_code == 422

    # Missing submitted_balance field
    res_missing = await authenticated_client.post(
        f"/physical-accounts/{account.id}/reconcile",
        json={"notes": "Missing balance"},
    )
    assert res_missing.status_code == 422


@pytest.mark.asyncio
async def test_reconcile_physical_account_rate_limit(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify POST /physical-accounts/{id}/reconcile enforces 10 requests/minute rate limit."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    account = await _seed_account_with_balance(db_session, "user@example.com", Decimal("1000.00"))

    payload = {"submitted_balance": "1000.00"}

    # 10 successful requests allowed
    for _ in range(10):
        res = await authenticated_client.post(f"/physical-accounts/{account.id}/reconcile", json=payload)
        assert res.status_code == 200

    # 11th request triggers 429 Too Many Requests
    exceeded_res = await authenticated_client.post(f"/physical-accounts/{account.id}/reconcile", json=payload)
    assert exceeded_res.status_code == 429
