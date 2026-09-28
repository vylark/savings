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
