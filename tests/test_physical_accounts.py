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
from src.main import app
from src.models.ledger import LedgerEntry, TransactionEvent
from src.models.physical_account import Institution, PhysicalAccount, PhysicalAccountShare
from src.models.user import User


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


async def _create_authenticated_user_client(
    email: str = "allocator@example.com",
    password: str = "SavingsPlatform2026!XyZ#9",
    first_name: str = "Alloc",
    last_name: str = "Ator",
    tax_band: TaxBand = TaxBand.BASIC,
) -> httpx.AsyncClient:
    """Helper to create, register, verify, and authenticate a distinct test user client."""
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


async def _seed_test_accounts_and_ledger(
    db_session: AsyncSession,
    owner_email: str = "user@example.com",
    allocator_email: str = "allocator@example.com",
) -> tuple[User, User, PhysicalAccount, PhysicalAccount]:
    """Helper to seed standard two-account scenario with owner and allocator shares."""
    owner = (await db_session.execute(select(User).where(User.__table__.c.email == owner_email))).scalars().one()
    allocator = (
        (await db_session.execute(select(User).where(User.__table__.c.email == allocator_email))).scalars().one()
    )
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    account_a = PhysicalAccount(
        name="Main Shared Account",
        institution_id=barclays.id,
        tax_wrapper=TaxWrapper.ISA,
        currency=Currency.GBP,
    )
    account_b = PhysicalAccount(
        name="USD Empty Account",
        institution_id=barclays.id,
        tax_wrapper=TaxWrapper.NONE,
        currency=Currency.USD,
    )
    db_session.add_all([account_a, account_b])
    await db_session.flush()

    db_session.add_all(
        [
            PhysicalAccountShare(user_id=owner.id, physical_account_id=account_a.id, role=AccountRole.OWNER),
            PhysicalAccountShare(user_id=allocator.id, physical_account_id=account_a.id, role=AccountRole.ALLOCATOR),
            PhysicalAccountShare(user_id=owner.id, physical_account_id=account_b.id, role=AccountRole.OWNER),
        ]
    )
    await db_session.flush()

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
    await db_session.commit()
    return owner, allocator, account_a, account_b


@pytest.mark.asyncio
async def test_list_physical_accounts_owner_visibility_and_empty_balance(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC1 (nested institution), AC2 (zero balance), and AC3 (owner total balance) via HTTP."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    allocator_client = await _create_authenticated_user_client()

    _, _, account_a, account_b = await _seed_test_accounts_and_ledger(db_session)

    res = await authenticated_client.get("/physical-accounts")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 2
    items = {item["name"]: item for item in data["items"]}

    # AC1 & AC3: Owner sees total balance £1500.00 and nested institution
    item_a = items["Main Shared Account"]
    assert item_a["balance"] == "1500.00"
    assert item_a["role"] == "OWNER"
    assert item_a["institution"]["name"] == "Barclays"
    assert item_a["currency"] == "GBP"

    # AC2: USD Empty Account has 0 ledger entries -> 0.00
    item_b = items["USD Empty Account"]
    assert item_b["balance"] == "0.00"
    assert item_b["currency"] == "USD"

    # Single-account retrieval as OWNER
    single_res = await authenticated_client.get(f"/physical-accounts/{account_a.id}")
    assert single_res.status_code == 200
    assert single_res.json()["balance"] == "1500.00"
    assert single_res.json()["role"] == "OWNER"

    await allocator_client.aclose()


@pytest.mark.asyncio
async def test_list_and_get_physical_accounts_allocator_privacy_http(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC4 (allocator privacy barrier) and AC5 (access boundary) end-to-end via HTTP as Allocator."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    allocator_client = await _create_authenticated_user_client(email="alloc.http@example.com")

    _, _, account_a, account_b = await _seed_test_accounts_and_ledger(
        db_session,
        allocator_email="alloc.http@example.com",
    )

    # 1. GET /physical-accounts as Allocator: strictly sees allocated slice (£500.00) and only shared account
    res = await allocator_client.get("/physical-accounts")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 1
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["id"] == str(account_a.id)
    assert item["role"] == "ALLOCATOR"
    assert item["balance"] == "500.00"
    assert item["institution"]["name"] == "Barclays"

    # 2. GET /physical-accounts/{id} as Allocator for shared account
    single_res = await allocator_client.get(f"/physical-accounts/{account_a.id}")
    assert single_res.status_code == 200
    single_data = single_res.json()
    assert single_data["role"] == "ALLOCATOR"
    assert single_data["balance"] == "500.00"

    # 3. GET /physical-accounts/{id} as Allocator for unshared account (AC5) -> 404
    unshared_res = await allocator_client.get(f"/physical-accounts/{account_b.id}")
    assert unshared_res.status_code == 404

    await allocator_client.aclose()


@pytest.mark.asyncio
async def test_list_physical_accounts_query_filtering(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC6 (query filtering by currency and tax wrapper) via HTTP."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    allocator_client = await _create_authenticated_user_client(email="filter.alloc@example.com")

    _, _, account_a, account_b = await _seed_test_accounts_and_ledger(
        db_session,
        allocator_email="filter.alloc@example.com",
    )

    # Filter ?currency=USD returns only USD account
    usd_res = await authenticated_client.get("/physical-accounts?currency=USD")
    assert usd_res.status_code == 200
    usd_data = usd_res.json()
    assert usd_data["total_count"] == 1
    assert usd_data["items"][0]["id"] == str(account_b.id)

    # Filter ?tax_wrapper=ISA returns only ISA account
    isa_res = await authenticated_client.get("/physical-accounts?tax_wrapper=ISA")
    assert isa_res.status_code == 200
    isa_data = isa_res.json()
    assert isa_data["total_count"] == 1
    assert isa_data["items"][0]["id"] == str(account_a.id)

    await allocator_client.aclose()


@pytest.mark.asyncio
async def test_get_physical_account_not_found(
    authenticated_client: httpx.AsyncClient,
) -> None:
    """Verify AC5: GET /physical-accounts/{id} returns 404 for non-existent account."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    res = await authenticated_client.get(f"/physical-accounts/{uuid.uuid4()}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_list_physical_accounts_currency_guard_in_bulk_aggregation(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify bulk aggregation ignores ledger entries whose currency does not match the account's currency."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    allocator_client = await _create_authenticated_user_client(email="currency.guard@example.com")

    owner, _, account_a, _ = await _seed_test_accounts_and_ledger(
        db_session,
        allocator_email="currency.guard@example.com",
    )

    # Add a mismatched currency ledger entry (USD entry on GBP account_a)
    mismatch_event = TransactionEvent(description="Mismatched currency entry")
    db_session.add(mismatch_event)
    await db_session.flush()

    db_session.add(
        LedgerEntry(
            transaction_id=mismatch_event.id,
            user_id=owner.id,
            physical_account_id=account_a.id,
            virtual_account_id=uuid.uuid4(),
            amount=Decimal("9999.00"),
            currency=Currency.USD,
        )
    )
    await db_session.commit()

    # Bulk query should still strictly return £1,500.00 for account_a, ignoring the $9,999.00 entry
    res = await authenticated_client.get("/physical-accounts")
    assert res.status_code == 200
    items = {item["name"]: item for item in res.json()["items"]}
    assert items["Main Shared Account"]["balance"] == "1500.00"

    # Single-account retrieval should also still strictly return £1,500.00
    single_res = await authenticated_client.get(f"/physical-accounts/{account_a.id}")
    assert single_res.status_code == 200
    assert single_res.json()["balance"] == "1500.00"

    await allocator_client.aclose()


@pytest.mark.asyncio
async def test_list_physical_accounts_rate_limit(
    authenticated_client: httpx.AsyncClient,
) -> None:
    """Verify GET /physical-accounts enforces the 60 requests/minute rate limit."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")

    for _ in range(60):
        res = await authenticated_client.get("/physical-accounts")
        assert res.status_code == 200

    # 61st request triggers HTTP 429 Too Many Requests
    exceeded_res = await authenticated_client.get("/physical-accounts")
    assert exceeded_res.status_code == 429


@pytest.mark.asyncio
async def test_share_physical_account_grant_success_and_visibility(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC1: Owner grants ALLOCATOR to User B by email; User B immediately sees account in GET /physical-accounts/."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    user_b_client = await _create_authenticated_user_client(
        email="user_b@example.com",
        first_name="Bob",
        last_name="Collaborator",
    )

    # 1. Owner creates account
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()
    create_res = await authenticated_client.post(
        "/physical-accounts",
        json={
            "name": "Family Vault",
            "institution_id": str(barclays.id),
            "tax_wrapper": "ISA",
            "currency": "GBP",
        },
    )
    assert create_res.status_code == 201
    account_id = create_res.json()["id"]

    # User B initially does NOT see the account
    user_b_list_before = await user_b_client.get("/physical-accounts")
    assert user_b_list_before.status_code == 200
    assert not any(item["id"] == account_id for item in user_b_list_before.json()["items"])

    # 2. Owner grants ALLOCATOR role to User B
    share_res = await authenticated_client.post(
        f"/physical-accounts/{account_id}/shares",
        json={"email": "user_b@example.com", "role": "ALLOCATOR"},
    )
    assert share_res.status_code == 201
    share_data = share_res.json()
    assert share_data["email"] == "user_b@example.com"
    assert share_data["first_name"] == "Bob"
    assert share_data["last_name"] == "Collaborator"
    assert share_data["role"] == "ALLOCATOR"
    assert "id" in share_data
    assert "created_at" in share_data

    # 3. User B immediately sees the account in GET /physical-accounts/
    user_b_list_after = await user_b_client.get("/physical-accounts")
    assert user_b_list_after.status_code == 200
    matching = [item for item in user_b_list_after.json()["items"] if item["id"] == account_id]
    assert len(matching) == 1
    assert matching[0]["name"] == "Family Vault"
    assert matching[0]["role"] == "ALLOCATOR"
    assert matching[0]["balance"] == "0.00"

    await user_b_client.aclose()


@pytest.mark.asyncio
async def test_share_physical_account_role_upgrade_and_downgrade(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC3: Subsequent share requests update collaborator role cleanly and affect balance visibility."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    collab_client = await _create_authenticated_user_client(email="collab_upgrade@example.com")

    # Seed accounts and ledger
    owner, collab, account_a, _ = await _seed_test_accounts_and_ledger(
        db_session,
        owner_email="user@example.com",
        allocator_email="collab_upgrade@example.com",
    )

    # Collab is currently ALLOCATOR; sees strictly own slice £500.00
    get_res = await collab_client.get(f"/physical-accounts/{account_a.id}")
    assert get_res.status_code == 200
    assert get_res.json()["balance"] == "500.00"
    assert get_res.json()["role"] == "ALLOCATOR"

    # Owner upgrades Collab to CO_OWNER
    upgrade_res = await authenticated_client.post(
        f"/physical-accounts/{account_a.id}/shares",
        json={"email": "collab_upgrade@example.com", "role": "CO_OWNER"},
    )
    assert upgrade_res.status_code == 201
    assert upgrade_res.json()["role"] == "CO_OWNER"

    # Collab now sees total balance £1500.00
    get_upgraded = await collab_client.get(f"/physical-accounts/{account_a.id}")
    assert get_upgraded.status_code == 200
    assert get_upgraded.json()["balance"] == "1500.00"
    assert get_upgraded.json()["role"] == "CO_OWNER"

    # Owner downgrades Collab back to ALLOCATOR
    downgrade_res = await authenticated_client.post(
        f"/physical-accounts/{account_a.id}/shares",
        json={"email": "collab_upgrade@example.com", "role": "ALLOCATOR"},
    )
    assert downgrade_res.status_code == 201
    assert downgrade_res.json()["role"] == "ALLOCATOR"

    # Collab now sees only £500.00 again
    get_downgraded = await collab_client.get(f"/physical-accounts/{account_a.id}")
    assert get_downgraded.status_code == 200
    assert get_downgraded.json()["balance"] == "500.00"
    assert get_downgraded.json()["role"] == "ALLOCATOR"

    await collab_client.aclose()


@pytest.mark.asyncio
async def test_share_physical_account_forbidden_for_allocator_and_co_owner(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC2: Non-owners (ALLOCATOR and CO_OWNER) receive 403 Forbidden when calling POST /shares."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    collab_client = await _create_authenticated_user_client(email="collab_forbidden@example.com")
    outsider_client = await _create_authenticated_user_client(email="outsider@example.com")

    _, _, account_a, _ = await _seed_test_accounts_and_ledger(
        db_session,
        owner_email="user@example.com",
        allocator_email="collab_forbidden@example.com",
    )

    # 1. ALLOCATOR calling POST /shares receives 403
    allocator_post = await collab_client.post(
        f"/physical-accounts/{account_a.id}/shares",
        json={"email": "outsider@example.com", "role": "ALLOCATOR"},
    )
    assert allocator_post.status_code == 403

    # Upgrade to CO_OWNER
    await authenticated_client.post(
        f"/physical-accounts/{account_a.id}/shares",
        json={"email": "collab_forbidden@example.com", "role": "CO_OWNER"},
    )

    # 2. CO_OWNER calling POST /shares also receives 403
    co_owner_post = await collab_client.post(
        f"/physical-accounts/{account_a.id}/shares",
        json={"email": "outsider@example.com", "role": "ALLOCATOR"},
    )
    assert co_owner_post.status_code == 403

    # 3. Outsider (non-member) receives 404
    outsider_post = await outsider_client.post(
        f"/physical-accounts/{account_a.id}/shares",
        json={"email": "user@example.com", "role": "ALLOCATOR"},
    )
    assert outsider_post.status_code == 404

    await collab_client.aclose()
    await outsider_client.aclose()


@pytest.mark.asyncio
async def test_share_physical_account_validation_guards(
    authenticated_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC4 (self-sharing), AC5 (OWNER role), AC6 (non-existent email), and unverified email guards."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")

    # Register an unverified user
    await client.post(
        "/auth/register",
        json={
            "email": "unverified_target@example.com",
            "password": "SavingsPlatform2026!XyZ#9",
            "first_name": "Unverified",
            "last_name": "User",
            "tax_band": TaxBand.BASIC.value,
        },
    )

    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()
    create_res = await authenticated_client.post(
        "/physical-accounts",
        json={
            "name": "Guarded Vault",
            "institution_id": str(barclays.id),
            "tax_wrapper": "NONE",
            "currency": "GBP",
        },
    )
    account_id = create_res.json()["id"]

    # 1. AC4: Self-sharing guard returns 400 Bad Request
    self_share_res = await authenticated_client.post(
        f"/physical-accounts/{account_id}/shares",
        json={"email": "user@example.com", "role": "ALLOCATOR"},
    )
    assert self_share_res.status_code == 400
    assert "yourself" in self_share_res.json()["detail"]

    # 2. Cannot assign OWNER role via share endpoint returns 422 Unprocessable Entity (schema boundary)
    owner_role_res = await authenticated_client.post(
        f"/physical-accounts/{account_id}/shares",
        json={"email": "collab_owner_attempt@example.com", "role": "OWNER"},
    )
    assert owner_role_res.status_code == 422

    # 3. AC6: Sharing with non-existent email returns 404 Not Found
    non_existent_res = await authenticated_client.post(
        f"/physical-accounts/{account_id}/shares",
        json={"email": "ghost_collaborator@example.com", "role": "ALLOCATOR"},
    )
    assert non_existent_res.status_code == 404
    assert "not found" in non_existent_res.json()["detail"]

    # 4. Sharing with unverified email returns 400 Bad Request
    unverified_res = await authenticated_client.post(
        f"/physical-accounts/{account_id}/shares",
        json={"email": "unverified_target@example.com", "role": "ALLOCATOR"},
    )
    assert unverified_res.status_code == 400
    assert "not verified" in unverified_res.json()["detail"]


@pytest.mark.asyncio
async def test_share_physical_account_rate_limit(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify POST /physical-accounts/{id}/shares enforces 30 requests/minute rate limit."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    collab_client = await _create_authenticated_user_client(email="rate_limit_collab@example.com")

    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()
    create_res = await authenticated_client.post(
        "/physical-accounts",
        json={
            "name": "Rate Limited Share Account",
            "institution_id": str(barclays.id),
            "tax_wrapper": "NONE",
            "currency": "GBP",
        },
    )
    account_id = create_res.json()["id"]

    for _ in range(30):
        res = await authenticated_client.post(
            f"/physical-accounts/{account_id}/shares",
            json={"email": "rate_limit_collab@example.com", "role": "ALLOCATOR"},
        )
        assert res.status_code == 201

    # 31st request triggers 429
    exceeded_res = await authenticated_client.post(
        f"/physical-accounts/{account_id}/shares",
        json={"email": "rate_limit_collab@example.com", "role": "ALLOCATOR"},
    )
    assert exceeded_res.status_code == 429

    await collab_client.aclose()


@pytest.mark.asyncio
async def test_list_account_shares_permissions_and_response(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify GET /physical-accounts/{id}/shares permissions (OWNER/CO_OWNER allowed, ALLOCATOR 403, outsider 404)."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    collab_client = await _create_authenticated_user_client(email="list_collab@example.com")
    outsider_client = await _create_authenticated_user_client(email="list_outsider@example.com")

    owner, collab, account_a, _ = await _seed_test_accounts_and_ledger(
        db_session,
        owner_email="user@example.com",
        allocator_email="list_collab@example.com",
    )

    # 1. Owner can list shares
    owner_list = await authenticated_client.get(f"/physical-accounts/{account_a.id}/shares")
    assert owner_list.status_code == 200
    shares_data = owner_list.json()
    assert len(shares_data) == 2
    emails = [s["email"] for s in shares_data]
    assert "user@example.com" in emails
    assert "list_collab@example.com" in emails

    # 2. Allocator receives 403 Forbidden
    allocator_list = await collab_client.get(f"/physical-accounts/{account_a.id}/shares")
    assert allocator_list.status_code == 403

    # Upgrade collaborator to CO_OWNER
    await authenticated_client.post(
        f"/physical-accounts/{account_a.id}/shares",
        json={"email": "list_collab@example.com", "role": "CO_OWNER"},
    )

    # 3. Co-Owner can list shares
    co_owner_list = await collab_client.get(f"/physical-accounts/{account_a.id}/shares")
    assert co_owner_list.status_code == 200
    assert len(co_owner_list.json()) == 2

    # 4. Outsider receives 404 Not Found
    outsider_list = await outsider_client.get(f"/physical-accounts/{account_a.id}/shares")
    assert outsider_list.status_code == 404

    await collab_client.aclose()
    await outsider_client.aclose()


@pytest.mark.asyncio
async def test_list_account_shares_rate_limit(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify GET /physical-accounts/{id}/shares enforces 60 requests/minute rate limit."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    create_res = await authenticated_client.post(
        "/physical-accounts",
        json={
            "name": "Rate Limited List Shares Account",
            "institution_id": str(barclays.id),
            "tax_wrapper": "NONE",
            "currency": "GBP",
        },
    )
    account_id = create_res.json()["id"]

    for _ in range(60):
        res = await authenticated_client.get(f"/physical-accounts/{account_id}/shares")
        assert res.status_code == 200

    # 61st request triggers 429
    exceeded_res = await authenticated_client.get(f"/physical-accounts/{account_id}/shares")
    assert exceeded_res.status_code == 429


@pytest.mark.asyncio
async def test_revoke_account_share_success_and_guardrails(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify AC5 (sole owner protection), revocation success (204), and post-revocation access termination."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    collab_client = await _create_authenticated_user_client(email="collab_revoke@example.com")

    owner, collab, account_a, _ = await _seed_test_accounts_and_ledger(
        db_session,
        owner_email="user@example.com",
        allocator_email="collab_revoke@example.com",
    )

    # 1. AC5: Owner cannot revoke primary ownership (400 Bad Request)
    self_del = await authenticated_client.delete(f"/physical-accounts/{account_a.id}/shares/{owner.id}")
    assert self_del.status_code == 400
    assert "primary ownership" in self_del.json()["detail"]

    # 2. Allocator attempts to revoke access -> 403 Forbidden
    allocator_del = await collab_client.delete(f"/physical-accounts/{account_a.id}/shares/{owner.id}")
    assert allocator_del.status_code == 403

    # 3. Owner revokes non-existent share -> 404 Not Found
    random_del = await authenticated_client.delete(f"/physical-accounts/{account_a.id}/shares/{uuid.uuid4()}")
    assert random_del.status_code == 404
    assert "not found" in random_del.json()["detail"]

    # 4. Successful revocation -> 204 No Content
    success_del = await authenticated_client.delete(f"/physical-accounts/{account_a.id}/shares/{collab.id}")
    assert success_del.status_code == 204

    # 5. Collaborator can no longer see the account
    get_res = await collab_client.get(f"/physical-accounts/{account_a.id}")
    assert get_res.status_code == 404

    list_res = await collab_client.get("/physical-accounts")
    assert list_res.status_code == 200
    assert not any(item["id"] == str(account_a.id) for item in list_res.json()["items"])

    await collab_client.aclose()


@pytest.mark.asyncio
async def test_revoke_account_share_rate_limit(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    seeded_institutions: list[Institution],  # noqa: ARG001
) -> None:
    """Verify DELETE /physical-accounts/{id}/shares/{target_id} enforces 30 requests/minute rate limit."""
    await _verify_authenticated_client(authenticated_client, email="user@example.com")
    barclays = (await db_session.execute(select(Institution).where(Institution.name == "Barclays"))).scalar_one()

    create_res = await authenticated_client.post(
        "/physical-accounts",
        json={
            "name": "Rate Limited Revoke Account",
            "institution_id": str(barclays.id),
            "tax_wrapper": "NONE",
            "currency": "GBP",
        },
    )
    account_id = create_res.json()["id"]

    target_uuid = uuid.uuid4()
    for _ in range(30):
        res = await authenticated_client.delete(f"/physical-accounts/{account_id}/shares/{target_uuid}")
        # Will return 404 because random target ID doesn't exist, but still counts toward rate limiter
        assert res.status_code == 404

    # 31st request triggers 429
    exceeded_res = await authenticated_client.delete(f"/physical-accounts/{account_id}/shares/{target_uuid}")
    assert exceeded_res.status_code == 429
