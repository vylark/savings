"""Integration tests for Story 2.1: Create Physical Account and List Institutions endpoints."""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import AccountRole
from src.core.mail import outbox
from src.db.seed import seed_institutions
from src.models.physical_account import Institution, PhysicalAccountShare
from src.models.user import User


async def _verify_authenticated_client(client: httpx.AsyncClient, email: str = "user@example.com") -> None:
    """Helper to verify the user account associated with an authenticated test client."""
    req_res = await client.post("/auth/request-verify-token", json={"email": email})
    assert req_res.status_code == 202
    token = outbox[-1]["body"].split("token is: ")[-1].strip()
    verify_res = await client.post("/auth/verify", json={"token": token})
    assert verify_res.status_code == 200


@pytest.mark.asyncio
async def test_list_institutions_and_search(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """Verify GET /institutions lists institutions alphabetically and supports substring search."""
    await seed_institutions(db_session)

    # 1. List all institutions
    res = await client.get("/institutions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 9
    names = [item["name"] for item in data]
    assert names == sorted(names)
    assert "Barclays" in names
    assert "Scottish Widows" in names

    # 2. Search by case-insensitive substring (also test trailing-slash route)
    search_res = await client.get("/institutions/?search=widows")
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert len(search_data) == 1
    assert search_data[0]["name"] == "Scottish Widows"
    assert search_data[0]["parent_institution_id"] is not None


@pytest.mark.asyncio
async def test_create_physical_account_success(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify POST /physical-accounts creates an account, links Institution, and grants OWNER share."""
    await _verify_authenticated_client(authenticated_client)
    await seed_institutions(db_session)

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
) -> None:
    """Verify creating an unwrapped account (tax_wrapper=NONE) with explicit owner_id."""
    await _verify_authenticated_client(authenticated_client)
    await seed_institutions(db_session)

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
    res = await authenticated_client.post("/physical-accounts/", json=payload)
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
    ],
)
async def test_create_physical_account_validation_errors(
    authenticated_client: httpx.AsyncClient,
    db_session: AsyncSession,
    invalid_overrides: dict[str, object],
) -> None:
    """Verify POST /physical-accounts returns 422 Unprocessable Entity on invalid payload fields."""
    await _verify_authenticated_client(authenticated_client)
    await seed_institutions(db_session)
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
) -> None:
    """Verify unauthenticated caller gets 401 and unverified caller gets 403 Forbidden."""
    await seed_institutions(db_session)
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
) -> None:
    """Verify POST /physical-accounts enforces the 20 requests/minute rate limit."""
    await _verify_authenticated_client(authenticated_client)
    await seed_institutions(db_session)
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
