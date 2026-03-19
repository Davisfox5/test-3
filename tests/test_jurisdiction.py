"""Tests for jurisdiction resolution."""

import pytest

from va_name_change.models import Address
from va_name_change.utils.jurisdiction import (
    JurisdictionError,
    list_supported_jurisdictions,
    resolve_jurisdiction,
)


def test_resolve_fairfax():
    addr = Address(street="123 Main St", city="Fairfax", county="Fairfax", zip_code="22030")
    court = resolve_jurisdiction(addr)
    assert court.fips_code == "059"
    assert "Fairfax" in court.name


def test_resolve_case_insensitive():
    addr = Address(street="1 St", city="Arlington", county="ARLINGTON", zip_code="22201")
    court = resolve_jurisdiction(addr)
    assert court.fips_code == "013"


def test_resolve_unknown_raises():
    addr = Address(street="1 St", city="Nowhere", county="Atlantis", zip_code="00000")
    with pytest.raises(JurisdictionError):
        resolve_jurisdiction(addr)


def test_list_supported():
    supported = list_supported_jurisdictions()
    assert "fairfax" in supported
    assert "richmond city" in supported
    assert len(supported) >= 5
