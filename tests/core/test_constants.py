"""Unit tests for core application constants and domain enumerations."""

from src.core.constants import TaxBand


def test_tax_band_enum_values() -> None:
    """Verify that TaxBand enum members match expected string values and member sets."""
    assert TaxBand.BASIC.value == "basic"
    assert TaxBand.HIGHER.value == "higher"
    assert TaxBand.ADDITIONAL.value == "additional"
    assert set(TaxBand) == {TaxBand.BASIC, TaxBand.HIGHER, TaxBand.ADDITIONAL}
