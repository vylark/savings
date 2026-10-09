"""Integration tests for Physical Account endpoints (Story 2.1 & Story 2.2)."""

import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import AccountRole, Currency, TaxBand, TaxWrapper
from src.core.mail import outbox
from src.models.ledger import LedgerEntry, TransactionEvent
from src.models.physical_account import Institution, PhysicalAccount, PhysicalAccountShare
from src.models.user import User
from src.services.physical_account import PhysicalAccountService


async def _verify_authenticated_client(client: httpx.AsyncClient, email: str = "user@example.com") -> None:
    """Helper to verify the user account associated with an authenticated test client."""
    req_res = await client.post("/auth/request-verify-token", json={"email": email})
    assert req_res.status_code == 202
    token = outbox[-1]["body"].split("token is: ")[-1].strip()
    verify_res = await client.post("/auth/verify", json={"token": token})
    assert verify_res.status_code == 200


@pytest.mark.asyncio
async def test_list_institutions_and_search(
    client: httpx.AsyncClient,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify GET /institutions lists institutions alphabetically and supports substring search."""
    # 1. List all institutions
    res = await client.get("/institutions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 9
    names = [item["name"] for item in data]
    assert names == sorted(names)
    assert "Barclays" in names
    assert "Scottish Widows" in names

    # 2. Search by case-insensitive substring
    search_res = await client.get("/institutions?search=widows")
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert len(search_data) == 1
    assert search_data[0]["name"] == "Scottish Widows"
    assert search_data[0]["parent_institution_id"] is not None


@pytest.mark.asyncio
async def test_create_physical_account_success(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify POST /physical-accounts creates an account, links Institution, and grants OWNER share."""
    await _verify_authenticated_client(authenticated_client)

    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    payload = {
        "name": "Barclays 1-Year Fixed Rate ISA",
        "institution_id": str(barclays.id),
        "tax_wrapper": "ISA",
        "interest_rate": "0.0450",
        "access_delay_days": 0,
        "maturity_date": "2027-09-30",
    }
    response = await authenticated_client.post("/physical-accounts", json=payload)
    assert response.status_code == 201
    body = response.json()

    assert body["name"] == "Barclays 1-Year Fixed Rate ISA"
    assert body["institution_id"] == str(barclays.id)
    assert body["institution"]["id"] == str(barclays.id)
    assert body["institution"]["name"] == "Barclays"
    assert body["tax_wrapper"] == "ISA"
    assert body["currency"] == "GBP"  # Default currency when omitted
    assert body["interest_rate"] == "0.0450"
    assert body["access_delay_days"] == 0
    assert body["maturity_date"] == "2027-09-30"
    assert body["role"] == "OWNER"
    assert body["balance"] == "0.00"
    assert "created_at" in body

    # Verify PhysicalAccountShare row exists in DB with role=OWNER
    account_uuid = uuid.UUID(body["id"])
    share = (
        await db_session.execute(
            select(PhysicalAccountShare).where(PhysicalAccountShare.physical_account_id == account_uuid)
        )
    ).scalar_one_or_none()
    assert share is not None
    assert share.role == AccountRole.OWNER


@pytest.mark.asyncio
async def test_create_physical_account_unwrapped_none_and_custom_owner(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify creating an unwrapped account (tax_wrapper=NONE) with explicit owner_id."""
    await _verify_authenticated_client(authenticated_client)

    monzo = (await db_session.execute(select(Institution).where(Institution.name == "Monzo"))).scalar_one()

    other_user = User(
        email="other.owner@example.com",
        hashed_password="hashed_password",
        first_name="Other",
        last_name="Owner",
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db_session.add(other_user)
    await db_session.flush()

    payload = {
        "name": "Everyday Notice Pot",
        "institution_id": str(monzo.id),
        "tax_wrapper": "NONE",
        "currency": "PHP",
        "access_delay_days": 30,
        "owner_id": str(other_user.id),
    }
    res = await authenticated_client.post("/physical-accounts", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["tax_wrapper"] == "NONE"
    assert data["currency"] == "PHP"
    assert data["access_delay_days"] == 30
    assert data["maturity_date"] is None

    # Verify owner_id was assigned on the share
    share = (
        await db_session.execute(
            select(PhysicalAccountShare).where(PhysicalAccountShare.physical_account_id == uuid.UUID(data["id"]))
        )
    ).scalar_one()
    assert share.user_id == other_user.id

    # Non-existent owner_id returns 404 Not Found
    bad_owner_payload = {**payload, "owner_id": str(uuid.uuid4())}
    bad_owner_res = await authenticated_client.post("/physical-accounts", json=bad_owner_payload)
    assert bad_owner_res.status_code == 404


@pytest.mark.asyncio
async def test_create_physical_account_invalid_institution_returns_404(
    authenticated_client: httpx.AsyncClient,
) -> None:
    """Verify POST /physical-accounts returns 404 Not Found if institution_id does not exist."""
    await _verify_authenticated_client(authenticated_client)

    payload = {
        "name": "Ghost Bank Saver",
        "institution_id": str(uuid.uuid4()),
        "tax_wrapper": "NONE",
    }
    res = await authenticated_client.post("/physical-accounts", json=payload)
    assert res.status_code == 404
    assert "does not exist" in res.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_overrides",
    [
        {"name": ""},
        {"name": "A" * 101},
        {"tax_wrapper": "INVALID_WRAPPER"},
        {"tax_wrapper": "STANDARD_SAVER"},
        {"currency": "JPY"},
        {"access_delay_days": -1},
        {"access_delay_days": 366},
        {"interest_rate": "-0.0100"},
        {"interest_rate": "1.5000"},
        {"maturity_date": "not-a-valid-date"},
        {"maturity_date": "2020-01-01"},
        {"maturity_date": date.today().isoformat()},
    ],
)
async def test_create_physical_account_validation_errors(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
    invalid_overrides: dict[str, object],
) -> None:
    """Verify POST /physical-accounts returns 422 Unprocessable Entity on invalid payload fields."""
    await _verify_authenticated_client(authenticated_client)
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    base_payload: dict[str, object] = {
        "name": "Valid Name",
        "institution_id": str(barclays.id),
        "tax_wrapper": "ISA",
        "currency": "GBP",
        "interest_rate": "0.0400",
        "access_delay_days": 0,
    }
    base_payload.update(invalid_overrides)

    res = await authenticated_client.post("/physical-accounts", json=base_payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_physical_account_security_guards(
    client: httpx.AsyncClient,
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify unauthenticated caller gets 401 and unverified caller gets 403 Forbidden."""
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    payload = {
        "name": "Protected Account",
        "institution_id": str(barclays.id),
        "tax_wrapper": "NONE",
    }

    # 1. Unverified authenticated user receives 403 Forbidden
    unverified_res = await authenticated_client.post("/physical-accounts", json=payload)
    assert unverified_res.status_code == 403

    # 2. Unauthenticated client receives 401 Unauthorized
    client.headers.pop("Authorization", None)
    unauth_res = await client.post("/physical-accounts", json=payload)
    assert unauth_res.status_code == 401


@pytest.mark.asyncio
async def test_create_physical_account_rate_limit(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify POST /physical-accounts enforces the 20 requests/minute rate limit."""
    await _verify_authenticated_client(authenticated_client)
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    for i in range(20):
        res = await authenticated_client.post(
            "/physical-accounts",
            json={
                "name": f"Account {i}",
                "institution_id": str(barclays.id),
                "tax_wrapper": "NONE",
            },
        )
        assert res.status_code == 201

    # 21st request within the same minute must return 429 Too Many Requests
    exceeded_res = await authenticated_client.post(
        "/physical-accounts",
        json={
            "name": "Account 21",
            "institution_id": str(barclays.id),
            "tax_wrapper": "NONE",
        },
    )
    assert exceeded_res.status_code == 429


@pytest.mark.asyncio
async def test_list_and_get_physical_accounts_ac_scenarios(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify Acceptance Criteria 1 to 6 for Story 2.2.

    AC1: Nested institution delivery
    AC2: Empty ledger balance = 0.00
    AC3: Owner full visibility (£1,500.00 = £1,000 owner + £500 allocator)
    AC4: Allocator privacy protection (£500.00 and role = ALLOCATOR)
    AC5: Access control (404 Not Found for non-member)
    AC6: Filtering (?currency=USD returns only USD-denominated accounts)
    """
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    owner = (await db_session.execute(select(User))).scalars().one()

    # Create Allocator user
    allocator = User(
        email="allocator@example.com",
        hashed_password="hashed_password",
        first_name="Alloc",
        last_name="Ator",
        tax_band=TaxBand.BASIC,
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db_session.add(allocator)
    await db_session.flush()

    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    # Create account A (GBP) shared with Owner and Allocator
    account_a = PhysicalAccount(
        name="Main Shared Account",
        institution_id=barclays.id,
        tax_wrapper=TaxWrapper.ISA,
        currency=Currency.GBP,
    )
    db_session.add(account_a)
    await db_session.flush()

    db_session.add_all(
        [
            PhysicalAccountShare(user_id=owner.id, physical_account_id=account_a.id, role=AccountRole.OWNER),
            PhysicalAccountShare(user_id=allocator.id, physical_account_id=account_a.id, role=AccountRole.ALLOCATOR),
        ]
    )
    await db_session.flush()

    # Add ledger entries: £1,000 by owner, £500 by allocator
    event_1 = TransactionEvent(description="Deposit 1")
    event_2 = TransactionEvent(description="Deposit 2")
    db_session.add_all([event_1, event_2])
    await db_session.flush()

    db_session.add_all(
        [
            LedgerEntry(
                transaction_id=event_1.id,
                user_id=owner.id,
                physical_account_id=account_a.id,
                virtual_account_id=uuid.uuid4(),
                amount=Decimal("1000.00"),
                currency=Currency.GBP,
            ),
            LedgerEntry(
                transaction_id=event_2.id,
                user_id=allocator.id,
                physical_account_id=account_a.id,
                virtual_account_id=uuid.uuid4(),
                amount=Decimal("500.00"),
                currency=Currency.GBP,
            ),
        ]
    )

    # Create account B (USD) with 0 ledger entries (AC2 & AC6)
    account_b = PhysicalAccount(
        name="USD Empty Account",
        institution_id=barclays.id,
        tax_wrapper=TaxWrapper.NONE,
        currency=Currency.USD,
    )
    db_session.add(account_b)
    await db_session.flush()
    db_session.add(PhysicalAccountShare(user_id=owner.id, physical_account_id=account_b.id, role=AccountRole.OWNER))
    await db_session.commit()

    # Test as OWNER
    res = await authenticated_client.get("/physical-accounts")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 2
    items = {item["name"]: item for item in data["items"]}

    # AC1 & AC3: Owner sees total balance £1500.00 and nested institution
    item_a = items["Main Shared Account"]
    assert item_a["balance"] == "1500.00"
    assert item_a["role"] == "OWNER"
    assert item_a["institution"]["id"] == str(barclays.id)
    assert item_a["institution"]["name"] == "Barclays"

    # AC2: Empty ledger balance = 0.00
    item_b = items["USD Empty Account"]
    assert item_b["balance"] == "0.00"
    assert item_b["currency"] == "USD"

    # AC6: Currency filtering
    usd_res = await authenticated_client.get("/physical-accounts?currency=USD")
    assert usd_res.status_code == 200
    usd_data = usd_res.json()
    assert usd_data["total_count"] == 1
    assert usd_data["items"][0]["id"] == str(account_b.id)

    # Tax wrapper filtering
    isa_res = await authenticated_client.get("/physical-accounts?tax_wrapper=ISA")
    assert isa_res.status_code == 200
    isa_data = isa_res.json()
    assert isa_data["total_count"] == 1
    assert isa_data["items"][0]["id"] == str(account_a.id)

    # AC5: Access control (non-existent or non-member)
    unknown_id = uuid.uuid4()
    not_found_res = await authenticated_client.get(f"/physical-accounts/{unknown_id}")
    assert not_found_res.status_code == 404

    # Single account retrieval as OWNER
    single_res = await authenticated_client.get(f"/physical-accounts/{account_a.id}")
    assert single_res.status_code == 200
    single_data = single_res.json()
    assert single_data["balance"] == "1500.00"
    assert single_data["role"] == "OWNER"
    assert single_data["institution"]["name"] == "Barclays"

    # AC4: Test as ALLOCATOR
    allocator_accounts = await PhysicalAccountService.get_user_accounts(
        db=db_session,
        user_id=allocator.id,
    )
    assert len(allocator_accounts) == 1
    assert allocator_accounts[0].id == account_a.id
    assert allocator_accounts[0].role == "ALLOCATOR"
    assert allocator_accounts[0].balance == Decimal("500.00")

    # Single balance check for allocator directly via service
    allocator_bal = await PhysicalAccountService.get_account_balance(
        db=db_session,
        account_id=account_a.id,
        role=AccountRole.ALLOCATOR,
        user_id=allocator.id,
    )
    assert allocator_bal == Decimal("500.00")
