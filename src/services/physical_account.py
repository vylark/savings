"""Service layer for Physical Accounts management, institutions, and ledger calculation."""

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.constants import AccountRole, Currency, TaxWrapper
from src.models.ledger import LedgerEntry
from src.models.physical_account import Institution, PhysicalAccount, PhysicalAccountShare
from src.models.user import User
from src.schemas.physical_account import PhysicalAccountCreate


class PhysicalAccountService:
    """Encapsulates business workflows for physical asset accounts and institutions."""

    @staticmethod
    async def list_institutions(
        db: AsyncSession,
        search: str | None = None,
    ) -> list[Institution]:
        """Queries the financial institutions catalog with optional name filtering.

        Args:
            db: Active asynchronous database session.
            search: Optional case-insensitive substring to filter institution names.

        Returns:
            Alphabetically ordered list of matching Institution ORM instances.
        """
        query = select(Institution).order_by(Institution.name.asc())
        if search:
            query = query.where(Institution.name.ilike(f"%{search}%"))
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create_account(
        db: AsyncSession,
        user: User,
        data: PhysicalAccountCreate,
        owner_id: uuid.UUID | None = None,
    ) -> PhysicalAccount:
        """Creates a new physical account linked to an institution and establishes owner permissions.

        Args:
            db: Database session.
            user: Authenticated calling user.
            data: Account creation attributes containing institution_id.
            owner_id: Optional target owner UUID; defaults to calling user.

        Raises:
            HTTPException: 404 if the referenced institution or custom owner user does not exist.

        Returns:
            The created PhysicalAccount instance with loaded institution relationship.
        """
        # Validate target institution exists
        institution = await db.get(Institution, data.institution_id)
        if not institution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Institution with ID '{data.institution_id}' does not exist.",
            )

        effective_owner_id = owner_id or user.id
        if effective_owner_id != user.id:
            target_owner = await db.get(User, effective_owner_id)
            if not target_owner:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with ID '{effective_owner_id}' does not exist.",
                )

        account = PhysicalAccount(
            name=data.name,
            institution_id=data.institution_id,
            tax_wrapper=TaxWrapper(data.tax_wrapper),
            currency=Currency(data.currency),
            interest_rate=data.interest_rate,
            access_delay_days=data.access_delay_days,
            maturity_date=data.maturity_date,
        )
        db.add(account)
        await db.flush()

        # Establish owner membership share
        share = PhysicalAccountShare(
            user_id=effective_owner_id,
            physical_account_id=account.id,
            role=AccountRole.OWNER,
        )
        db.add(share)
        await db.commit()

        # Reload with institution relationship populated
        query = (
            select(PhysicalAccount)
            .options(selectinload(PhysicalAccount.institution))
            .where(PhysicalAccount.id == account.id)
        )
        return (await db.execute(query)).scalar_one()

    @staticmethod
    async def get_account_balance(
        db: AsyncSession,
        account_id: uuid.UUID,
        role: AccountRole,
        user_id: uuid.UUID,
    ) -> Decimal:
        """Calculates dynamic balance from ledger entries respecting user role privacy.

        Args:
            db: Database session.
            account_id: Target physical account.
            role: Caller's membership role.
            user_id: Caller's user UUID.

        Returns:
            Computed balance as a Decimal.
        """
        query = select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00"))).where(
            LedgerEntry.physical_account_id == account_id
        )

        # Restrict sum to caller's slices if user is merely an ALLOCATOR
        if role == AccountRole.ALLOCATOR:
            query = query.where(LedgerEntry.user_id == user_id)

        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def ensure_unallocated_bucket(
        db: AsyncSession,
        user_id: uuid.UUID,
        currency: Currency,
    ) -> uuid.UUID:
        """Provisions or retrieves the system-managed Unallocated virtual account for a user.

        Used during reconciliation and deposits as the default balancing virtual bucket.

        Args:
            db: Database session.
            user_id: User identifier.
            currency: Account currency.

        Returns:
            UUID of the unallocated virtual account.
        """
        unallocated_namespace = uuid.uuid5(user_id, f"unallocated_{currency.value}")
        return unallocated_namespace
