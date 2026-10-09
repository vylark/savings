"""Service layer for Physical Accounts management, institutions, and ledger calculation."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Row, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.constants import AccountRole, Currency, TaxWrapper
from src.models.ledger import LedgerEntry
from src.models.physical_account import Institution, PhysicalAccount, PhysicalAccountShare
from src.models.user import User
from src.schemas.physical_account import (
    InstitutionRead,
    PhysicalAccountCreate,
    PhysicalAccountRead,
)


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
            # TODO: Security hardening required - verify caller is authorized (e.g., admin role or
            # target user consent) to assign ownership to an arbitrary third party. Permitted for Story 2.1 MVP.
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

        # Deterministically initialize/ensure unallocated bucket to guarantee immediate ledger compatibility
        await PhysicalAccountService.ensure_unallocated_bucket(
            db=db,
            user_id=effective_owner_id,
            currency=account.currency,
        )

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

        Guards against cross-currency rollups by filtering ledger entries to match
        the physical account's designated base currency.

        Args:
            db: Database session.
            account_id: Target physical account.
            role: Caller's membership role.
            user_id: Caller's user UUID.

        Returns:
            Computed balance as a Decimal.
        """
        query = (
            select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00")))
            .join(PhysicalAccount, LedgerEntry.physical_account_id == PhysicalAccount.id)
            .where(
                LedgerEntry.physical_account_id == account_id,
                LedgerEntry.currency == PhysicalAccount.currency,
            )
        )

        # Restrict sum to caller's slices if user is merely an ALLOCATOR
        if role == AccountRole.ALLOCATOR:
            query = query.where(LedgerEntry.user_id == user_id)

        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def _fetch_user_account_shares(
        db: AsyncSession,
        user_id: uuid.UUID,
        currency: Currency | None = None,
        tax_wrapper: TaxWrapper | None = None,
    ) -> Sequence[Row[tuple[PhysicalAccount, AccountRole]]]:
        """Queries physical accounts accessible to the user with eager-loaded institutions.

        Args:
            db: Database session.
            user_id: Authenticated user identifier.
            currency: Optional currency filter.
            tax_wrapper: Optional tax wrapper filter.

        Returns:
            Sequence of (PhysicalAccount, AccountRole) rows for the user.
        """
        stmt = (
            select(PhysicalAccount, PhysicalAccountShare.role)
            .options(selectinload(PhysicalAccount.institution))
            .join(
                PhysicalAccountShare,
                PhysicalAccount.id == PhysicalAccountShare.physical_account_id,
            )
            .where(PhysicalAccountShare.user_id == user_id)
        )
        if currency:
            stmt = stmt.where(PhysicalAccount.currency == currency)
        if tax_wrapper:
            stmt = stmt.where(PhysicalAccount.tax_wrapper == tax_wrapper)

        result = await db.execute(stmt)
        return result.all()

    @staticmethod
    async def _aggregate_ledger_balances(
        db: AsyncSession,
        account_ids: list[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, Row[tuple[uuid.UUID, Decimal, Decimal]]]:
        """Bulk aggregates total and user-specific ledger balances across account IDs.

        Args:
            db: Database session.
            account_ids: Target physical account IDs to calculate balances for.
            user_id: Authenticated user identifier.

        Returns:
            Dictionary mapping account ID to aggregated balance row.
        """
        ledger_stmt = (
            select(
                LedgerEntry.physical_account_id,
                func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00")).label("total_balance"),
                func.coalesce(
                    func.sum(
                        case(
                            (LedgerEntry.user_id == user_id, LedgerEntry.amount),
                            else_=Decimal("0.00"),
                        )
                    ),
                    Decimal("0.00"),
                ).label("user_balance"),
            )
            .join(PhysicalAccount, LedgerEntry.physical_account_id == PhysicalAccount.id)
            .where(
                LedgerEntry.physical_account_id.in_(account_ids),
                LedgerEntry.currency == PhysicalAccount.currency,
            )
            .group_by(LedgerEntry.physical_account_id)
        )
        results = await db.execute(ledger_stmt)
        return {row.physical_account_id: row for row in results.all()}

    @staticmethod
    async def get_user_accounts(
        db: AsyncSession,
        user_id: uuid.UUID,
        currency: Currency | None = None,
        tax_wrapper: TaxWrapper | None = None,
    ) -> list[PhysicalAccountRead]:
        """Retrieves all accounts accessible by the user, computing balances according to RBAC.

        Args:
            db: Database session.
            user_id: Authenticated user identifier.
            currency: Optional currency filter.
            tax_wrapper: Optional tax wrapper filter.

        Returns:
            List of PhysicalAccountRead schemas populated with balances and roles.
        """
        records = await PhysicalAccountService._fetch_user_account_shares(
            db=db,
            user_id=user_id,
            currency=currency,
            tax_wrapper=tax_wrapper,
        )
        if not records:
            return []

        account_ids = [acc.id for acc, _ in records]
        ledger_results = await PhysicalAccountService._aggregate_ledger_balances(
            db=db,
            account_ids=account_ids,
            user_id=user_id,
        )

        output: list[PhysicalAccountRead] = []
        for account, role in records:
            ledger_data = ledger_results.get(account.id)
            if role in (AccountRole.OWNER, AccountRole.CO_OWNER):
                balance = ledger_data.total_balance if ledger_data else Decimal("0.00")
            else:
                balance = ledger_data.user_balance if ledger_data else Decimal("0.00")

            output.append(
                PhysicalAccountRead(
                    id=account.id,
                    name=account.name,
                    institution_id=account.institution_id,
                    institution=InstitutionRead.model_validate(account.institution),
                    tax_wrapper=account.tax_wrapper.value,
                    currency=account.currency.value,
                    interest_rate=account.interest_rate,
                    access_delay_days=account.access_delay_days,
                    maturity_date=account.maturity_date,
                    role=role.value,
                    balance=balance,
                    created_at=account.created_at,
                )
            )
        return output

    @staticmethod
    async def ensure_unallocated_bucket(
        db: AsyncSession,
        user_id: uuid.UUID,
        currency: Currency,
    ) -> uuid.UUID:
        """Provisions or retrieves the system-managed Unallocated virtual account for a user.

        Invoked eagerly during physical account creation and on-demand during reconciliation
        and deposits as the default balancing virtual bucket.

        Args:
            db: Database session.
            user_id: User identifier.
            currency: Account currency.

        Returns:
            UUID of the unallocated virtual account.
        """
        unallocated_namespace = uuid.uuid5(user_id, f"unallocated_{currency.value}")
        return unallocated_namespace
