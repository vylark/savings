"""Pydantic schemas for physical account and institution validation and serialization."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.constants import AccountRoleType, CurrencyType, TaxWrapperType


class InstitutionRead(BaseModel):
    """Public details of a financial institution.

    Attributes:
        id: Primary key UUID of the financial institution.
        name: Official provider name.
        logo_url: Optional asset URI for UI display.
        parent_institution_id: Optional parent banking group UUID for FSCS aggregation.
    """

    id: uuid.UUID
    name: str
    logo_url: str | None = None
    parent_institution_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class PhysicalAccountCreate(BaseModel):
    """Payload schema for registering a new physical account.

    Attributes:
        name: User-assigned account name (1 to 100 characters).
        institution_id: UUID of the financial institution.
        tax_wrapper: Legal tax wrapper (NONE, ISA, SIPP, GIA).
        currency: Base currency code (defaults to 'GBP').
        interest_rate: Annual interest rate as decimal (e.g., 0.0450 for 4.50%), optional.
        access_delay_days: Notice period or withdrawal delay in business days (0 to 365).
        maturity_date: Optional fixed-term maturity date for fixed rate bonds/ISAs.
        owner_id: Optional explicit owner UUID (defaults to authenticated caller).
            Security Note / TODO: Arbitrary cross-user attribution is permitted for Story 2.1 MVP
            but must be hardened (e.g., admin-only or target user consent) in future stories.
    """

    name: str = Field(..., min_length=1, max_length=100, description="User-assigned account name")
    institution_id: uuid.UUID = Field(..., description="UUID of the financial institution")
    tax_wrapper: TaxWrapperType = Field(..., description="Legal tax wrapper (NONE, ISA, SIPP, GIA)")
    currency: CurrencyType = Field(default="GBP", description="Base currency code")
    interest_rate: Decimal | None = Field(
        default=None,
        ge=Decimal("0.0000"),
        le=Decimal("1.0000"),
        description="Annual interest rate as decimal (e.g., 0.0450 for 4.50%)",
    )
    access_delay_days: int = Field(
        default=0,
        ge=0,
        le=365,
        description="Notice period or withdrawal delay in business days",
    )
    maturity_date: date | None = Field(
        default=None,
        description="Optional fixed-term maturity date for fixed rate bonds/ISAs",
    )
    owner_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional explicit owner UUID (defaults to authenticated caller). "
            "TODO: Security hardening required - assigning arbitrary third-party owners "
            "is permitted in Story 2.1 MVP but requires admin authorization or target user consent "
            "in future stories."
        ),
    )

    @field_validator("maturity_date")
    @classmethod
    def validate_maturity_date_in_future(cls, value: date | None) -> date | None:
        """Validates that maturity_date, if specified, is strictly in the future.

        Args:
            value: Date supplied in request payload.

        Raises:
            ValueError: If maturity date is today or in the past.

        Returns:
            Validated date or None.
        """
        if value is not None and value <= date.today():
            raise ValueError("Maturity date must be in the future.")
        return value


class PhysicalAccountRead(BaseModel):
    """Response schema representing a physical account with caller access tier and balance.

    Attributes:
        id: Primary key UUID of the physical account.
        name: User-assigned account name.
        institution_id: Foreign key UUID of the linked Institution.
        institution: Nested InstitutionRead details.
        tax_wrapper: Legal tax wrapper classification.
        currency: Base currency denomination.
        interest_rate: Annual interest rate as decimal, if applicable.
        access_delay_days: Notice period or withdrawal delay in business days.
        maturity_date: Fixed-term maturity date, if applicable.
        role: Caller's RBAC access role on the account.
        balance: Calculated balance from ledger entries.
        created_at: UTC timestamp when the account was created.
    """

    id: uuid.UUID
    name: str
    institution_id: uuid.UUID
    institution: InstitutionRead
    tax_wrapper: TaxWrapperType
    currency: CurrencyType
    interest_rate: Decimal | None
    access_delay_days: int
    maturity_date: date | None = None
    role: AccountRoleType
    balance: Decimal = Field(default=Decimal("0.00"), description="Calculated balance from ledger")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PhysicalAccountListResponse(BaseModel):
    """Collection list response containing physical accounts and their calculated balances.

    Attributes:
        items: List of physical accounts accessible to the caller.
        total_count: Total number of accessible physical accounts.
    """

    items: list[PhysicalAccountRead]
    total_count: int
