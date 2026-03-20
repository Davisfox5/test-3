"""Tests for the filing agent."""

from datetime import date

from va_name_change.agents.filing import format_instructions, prepare_filing, get_filing_instructions
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


def test_all_courts_file_in_person():
    """All name change petitions are filed in person or by mail."""
    for county in ("Fairfax", "Richmond City", "Roanoke City"):
        p = _petition(county)
        fi = prepare_filing(p)
        assert fi.method == "in_person"
        assert p.status == PetitionStatus.FILED


def test_instructions_include_oath_info():
    p = _petition("Fairfax")
    fi = get_filing_instructions(p)
    assert "under oath" in fi.oath_info.lower()
    assert "notary" in fi.oath_info.lower()


def test_instructions_include_publication_info():
    p = _petition("Roanoke City")
    fi = get_filing_instructions(p)
    assert "publication" in fi.publication_info.lower() or "newspaper" in fi.publication_info.lower()


def test_instructions_include_background_check_info():
    p = _petition("Fairfax")
    fi = get_filing_instructions(p)
    assert "felony" in fi.background_check_info.lower()
    assert "fingerprint" in fi.background_check_info.lower()  # mentions it's NOT required


def test_format_instructions():
    p = _petition("Fairfax")
    fi = prepare_filing(p)
    text = format_instructions(fi)
    assert "IN_PERSON" in text
    assert "Fairfax" in text
    assert "Oath" in text
    assert "Publication" in text
