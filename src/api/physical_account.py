"""API router for Physical Account and Institution endpoints."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.physical_account import require_account_member
from src.core.constants import Currency, TaxWrapper
from src.core.limiter import limiter
from src.core.users import current_verified_user
from src.db.session import get_db_session
from src.models.physical_account import PhysicalAccount, PhysicalAccountShare
from src.models.user import User
from src.schemas.physical_account import (
    InstitutionRead,
    PhysicalAccountCreate,
    PhysicalAccountListResponse,
    PhysicalAccountRead,
)
from src.services.physical_account import PhysicalAccountService

router = APIRouter(tags=["Physical Accounts & Institutions"])


@router.get(
    "/institutions",
    response_model=list[InstitutionRead],
    summary="List available financial institutions",
)
@limiter.limit("60/minute")
async def list_institutions(
    request: Request,  # noqa: ARG001
    search: str | None = Query(default=None, description="Filter institutions by name substring"),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> list[InstitutionRead]:
    """Retrieves supported financial institutions catalog.

    Args:
        request: FastAPI Request object for slowapi rate limiting.
        search: Optional case-insensitive substring filter for institution name.
        db: Asynchronous database session.

    Returns:
        List of matching InstitutionRead objects ordered alphabetically by name.
    """
    institutions = await PhysicalAccountService.list_institutions(db=db, search=search)
    return [InstitutionRead.model_validate(inst) for inst in institutions]


@router.post(
    "/physical-accounts",
    response_model=PhysicalAccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new physical account",
)
@limiter.limit("20/minute")
async def create_physical_account(
    request: Request,  # noqa: ARG001
    payload: PhysicalAccountCreate,
    user: User = Depends(current_verified_user),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PhysicalAccountRead:
    """Creates a new physical asset account linked to an institution.

    Args:
        request: FastAPI Request object for slowapi rate limiting.
        payload: Account parameters (name, institution_id, tax wrapper, currency, etc.).
        user: Authenticated and verified calling user.
        db: Asynchronous database session.

    Returns:
        The newly created PhysicalAccount details with OWNER role and 0.00 initial balance.
    """
    account = await PhysicalAccountService.create_account(
        db=db,
        user=user,
        data=payload,
        owner_id=payload.owner_id,
    )

    return PhysicalAccountRead(
        id=account.id,
        name=account.name,
        institution_id=account.institution_id,
        institution=InstitutionRead.model_validate(account.institution),
        tax_wrapper=account.tax_wrapper.value,
        currency=account.currency.value,
        interest_rate=account.interest_rate,
        access_delay_days=account.access_delay_days,
        maturity_date=account.maturity_date,
        role="OWNER",
        balance=Decimal("0.00"),
        created_at=account.created_at,
    )


@router.get(
    "/physical-accounts",
    response_model=PhysicalAccountListResponse,
    summary="List all accessible physical accounts with ledger balances",
)
@limiter.limit("60/minute")
async def list_physical_accounts(
    request: Request,  # noqa: ARG001
    currency: Currency | None = Query(default=None, description="Filter by currency denomination"),  # noqa: B008
    tax_wrapper: TaxWrapper | None = Query(default=None, description="Filter by legal tax wrapper"),  # noqa: B008
    user: User = Depends(current_verified_user),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PhysicalAccountListResponse:
    """Lists all physical accounts the caller has permission to view.

    Balances are calculated dynamically from the unified ledger. Allocator roles
    will only see balances corresponding to their own allocations.

    Args:
        request: FastAPI Request object for slowapi rate limiting.
        currency: Optional filter by currency denomination.
        tax_wrapper: Optional filter by legal tax wrapper.
        user: Authenticated and verified calling user.
        db: Asynchronous database session.

    Returns:
        Collection list containing accessible physical accounts with dynamic balances.
    """
    accounts = await PhysicalAccountService.get_user_accounts(
        db=db,
        user_id=user.id,
        currency=currency,
        tax_wrapper=tax_wrapper,
    )
    return PhysicalAccountListResponse(items=accounts, total_count=len(accounts))


@router.get(
    "/physical-accounts/{account_id}",
    response_model=PhysicalAccountRead,
    summary="Retrieve single physical account details",
)
@limiter.limit("60/minute")
async def get_physical_account(
    request: Request,  # noqa: ARG001
    resolved: tuple[PhysicalAccount, PhysicalAccountShare] = Depends(require_account_member),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> PhysicalAccountRead:
    """Retrieves details of a specific physical account.

    Caller must be an OWNER, CO_OWNER, or ALLOCATOR.

    Args:
        request: FastAPI Request object for slowapi rate limiting.
        resolved: Tuple of resolved physical account and caller's share relationship.
        db: Asynchronous database session.

    Returns:
        PhysicalAccountRead response including computed ledger balance and member role.
    """
    account, share = resolved
    balance = await PhysicalAccountService.get_account_balance(
        db=db,
        account_id=account.id,
        role=share.role,
        user_id=share.user_id,
    )
    return PhysicalAccountRead(
        id=account.id,
        name=account.name,
        institution_id=account.institution_id,
        institution=InstitutionRead.model_validate(account.institution),
        tax_wrapper=account.tax_wrapper.value,
        currency=account.currency.value,
        interest_rate=account.interest_rate,
        access_delay_days=account.access_delay_days,
        maturity_date=account.maturity_date,
        role=share.role.value,
        balance=balance,
        created_at=account.created_at,
    )
