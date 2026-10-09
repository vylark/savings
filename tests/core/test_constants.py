"""Unit tests for core application constants and domain enumerations."""

from src.core.constants import AccountRole, Currency, TaxBand, TaxWrapper


def test_tax_band_enum_values() -> None:
    """Verify that TaxBand enum members match expected string values and member sets."""
    assert TaxBand.BASIC.value == "basic"
    assert TaxBand.HIGHER.value == "higher"
    assert TaxBand.ADDITIONAL.value == "additional"
    assert set(TaxBand) == {TaxBand.BASIC, TaxBand.HIGHER, TaxBand.ADDITIONAL}


def test_tax_wrapper_enum_values() -> None:
    """Verify that TaxWrapper enum members match expected string values and member sets."""
    assert TaxWrapper.NONE.value == "NONE"
    assert TaxWrapper.ISA.value == "ISA"
    assert TaxWrapper.SIPP.value == "SIPP"
    assert TaxWrapper.GIA.value == "GIA"
    assert set(TaxWrapper) == {TaxWrapper.NONE, TaxWrapper.ISA, TaxWrapper.SIPP, TaxWrapper.GIA}


def test_currency_enum_values() -> None:
    """Verify that Currency enum members match expected ISO currency codes."""
    assert Currency.GBP.value == "GBP"
    assert Currency.USD.value == "USD"
    assert Currency.EUR.value == "EUR"
    assert Currency.PHP.value == "PHP"
    assert set(Currency) == {Currency.GBP, Currency.USD, Currency.EUR, Currency.PHP}


def test_account_role_enum_values() -> None:
    """Verify that AccountRole enum members match expected RBAC role tiers."""
    assert AccountRole.OWNER.value == "OWNER"
    assert AccountRole.CO_OWNER.value == "CO_OWNER"
    assert AccountRole.ALLOCATOR.value == "ALLOCATOR"
    assert set(AccountRole) == {AccountRole.OWNER, AccountRole.CO_OWNER, AccountRole.ALLOCATOR}
