"""Tests for the filing agent."""

from datetime import date

from va_name_change.agents.filing import format_instructions, prepare_filing
from va_name_change.models import Address, NameChangePetition, PetitionStatus
from va_name_change.utils.jurisdiction import resolve_jurisdiction


def _petition(county: str) -> NameChangePetition:
    addr = Address(street="1 St", city=county, county=county, zip_code="00000")
    p = NameChangePetition(
        current_legal_name="A B",
        desired_name="C D",
        dob=date(2000, 1, 1),
        address=addr,
        jurisdiction=resolve_jurisdiction(addr),
    )
    p.status = PetitionStatus.FORMS_READY
    return p


def test_efiling_jurisdiction():
    p = _petition("Fairfax")
    fi = prepare_filing(p)
    assert fi.method == "efiling"
    assert fi.efiling_url
    assert p.status == PetitionStatus.FILED


def test_in_person_jurisdiction():
    p = _petition("Richmond City")
    fi = prepare_filing(p)
    assert fi.method == "in_person"
    assert fi.efiling_url is None
    assert p.status == PetitionStatus.FILED


def test_format_instructions():
    p = _petition("Fairfax")
    fi = prepare_filing(p)
    text = format_instructions(fi)
    assert "EFILING" in text
    assert "Fairfax" in text
