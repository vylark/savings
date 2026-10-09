"""Core application domain constants, enums, and type aliases.

This module defines shared domain types and constants used across API request/response
schemas, database models, and financial calculation logic.
"""

from enum import StrEnum
from typing import Literal

TaxBandType = Literal["basic", "higher", "additional"]
"""Type alias representing allowed UK tax band string literals for schema validation."""


class TaxBand(StrEnum):
    """Enumeration of supported UK income tax bands.

    Attributes:
        BASIC: Basic rate tax band.
        HIGHER: Higher rate tax band.
        ADDITIONAL: Additional rate tax band.
    """

    BASIC = "basic"
    HIGHER = "higher"
    ADDITIONAL = "additional"


TaxWrapperType = Literal["NONE", "ISA", "SIPP", "GIA"]
"""Type alias representing allowed UK tax wrapper classifications."""

CurrencyType = Literal["GBP", "USD", "EUR", "PHP"]
"""Type alias representing supported 3-letter currency ISO codes."""

AccountRoleType = Literal["OWNER", "CO_OWNER", "ALLOCATOR"]
"""Type alias representing physical account sharing roles."""

ShareableRoleType = Literal["CO_OWNER", "ALLOCATOR"]
"""Type alias representing collaborator roles that can be granted via account sharing."""


class TaxWrapper(StrEnum):
    """Enumeration of supported UK tax wrappers.

    Attributes:
        NONE: Unwrapped taxable account (no tax wrapper).
        ISA: Individual Savings Account (tax-free interest and capital gains).
        SIPP: Self-Invested Personal Pension (tax-relieved retirement savings).
        GIA: General Investment Account (unwrapped taxable trading).
    """

    NONE = "NONE"
    ISA = "ISA"
    SIPP = "SIPP"
    GIA = "GIA"


class Currency(StrEnum):
    """Enumeration of supported multi-currency codes.

    Attributes:
        GBP: British Pound Sterling.
        USD: United States Dollar.
        EUR: Euro.
        PHP: Philippine Peso.
    """

    GBP = "GBP"
    USD = "USD"
    EUR = "EUR"
    PHP = "PHP"


class AccountRole(StrEnum):
    """Enumeration of access control roles for shared physical accounts.

    Attributes:
        OWNER: Account creator or primary legal owner. Full administrative rights.
        CO_OWNER: Joint account holder with visibility into total balances and reconciliation rights.
        ALLOCATOR: External user permitted only to allocate virtual goals into this account.
    """

    OWNER = "OWNER"
    CO_OWNER = "CO_OWNER"
    ALLOCATOR = "ALLOCATOR"
