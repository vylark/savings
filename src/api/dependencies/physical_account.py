"""FastAPI dependencies for Physical Account authorization and resolution."""

# cspell:words selectinload

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.constants import AccountRole
from src.core.users import current_verified_user
from src.db.session import get_db_session
from src.models.physical_account import PhysicalAccount, PhysicalAccountShare
from src.models.user import User


class AccountAccessChecker:
    """Dependency callable to verify user permissions on a target physical account.

    Attributes:
        allowed_roles: Optional list of permitted AccountRole tiers. If None, any member role is permitted.
    """

    def __init__(self, allowed_roles: list[AccountRole] | None = None) -> None:
        """Initializes checker with permitted role tiers.

        Args:
            allowed_roles: List of allowed roles. If None, any member role is permitted.
        """
        self.allowed_roles = allowed_roles

    async def __call__(
        self,
        account_id: Annotated[uuid.UUID, Path(description="Physical Account UUID")],
        current_user: Annotated[User, Depends(current_verified_user)],
        db: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> tuple[PhysicalAccount, PhysicalAccountShare]:
        """Resolves physical account and validates caller membership role.

        Args:
            account_id: Target physical account UUID from path parameter.
            current_user: Authenticated and verified calling user.
            db: Active asynchronous database session.

        Returns:
            Tuple of (PhysicalAccount, PhysicalAccountShare) for the verified member.

        Raises:
            HTTPException: 404 if account does not exist or user has no share record.
            HTTPException: 403 if user's share role lacks sufficient privileges.
        """
        query = (
            select(PhysicalAccount, PhysicalAccountShare)
            .options(selectinload(PhysicalAccount.institution))
            .join(
                PhysicalAccountShare,
                PhysicalAccount.id == PhysicalAccountShare.physical_account_id,
            )
            .where(
                PhysicalAccount.id == account_id,
                PhysicalAccountShare.user_id == current_user.id,
            )
        )
        result = await db.execute(query)
        record = result.first()

        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Physical account not found or access denied.",
            )

        account, share = record

        if self.allowed_roles and share.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of {[r.value for r in self.allowed_roles]} permissions.",
            )

        return account, share


# Pre-configured dependency shortcuts
require_account_member = AccountAccessChecker()
require_account_reconciler = AccountAccessChecker([AccountRole.OWNER, AccountRole.CO_OWNER])
require_account_owner = AccountAccessChecker([AccountRole.OWNER])
