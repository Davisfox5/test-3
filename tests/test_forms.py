"""Tests for the forms agent."""

import os
from datetime import date

from va_name_change.agents.forms import generate_all_forms
from va_name_change.models import (
    Address,
    DocumentType,
    NameChangePetition,
    PetitionStatus,
)
from va_name_change.utils.jurisdiction import resolve_jurisdiction


def _make_petition() -> NameChangePetition:
    addr = Address(street="123 Main St", city="Fairfax", county="Fairfax", zip_code="22030")
    p = NameChangePetition(
        current_legal_name="John Smith",
        desired_name="Jane Smith",
        reason="personal preference",
        dob=date(1990, 1, 15),
        ssn_encrypted="encrypted",
        address=addr,
        jurisdiction=resolve_jurisdiction(addr),
    )
    return p


def test_generate_all_forms(tmp_path, monkeypatch):
    monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))
    p = _make_petition()
    docs = generate_all_forms(p)

    assert len(docs) >= 3  # CC-1411, cover letter, publication, SS-5
    assert p.status == PetitionStatus.FORMS_READY

    doc_types = {d.doc_type for d in docs}
    assert DocumentType.PETITION_CC1411 in doc_types
    assert DocumentType.COVER_LETTER in doc_types
    assert DocumentType.SSA_SS5 in doc_types

    for doc in docs:
        assert os.path.isfile(doc.file_path)
        assert os.path.getsize(doc.file_path) > 100  # non-trivial PDF
