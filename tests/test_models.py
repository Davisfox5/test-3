"""Tests for core data models."""

from datetime import date

from va_name_change.models import (
    Address,
    DownstreamStatus,
    DownstreamUpdate,
    Document,
    DocumentType,
    NameChangePetition,
    PetitionStatus,
)


def test_petition_defaults():
    p = NameChangePetition()
    assert p.status == PetitionStatus.INTAKE
    assert p.documents == []
    assert p.downstream_updates == []
    assert len(p.petition_id) == 12


def test_advance():
    p = NameChangePetition()
    p.advance(PetitionStatus.FORMS_READY)
    assert p.status == PetitionStatus.FORMS_READY


def test_add_document():
    p = NameChangePetition()
    doc = Document(doc_type=DocumentType.PETITION_CC1411, file_path="/tmp/test.txt")
    p.add_document(doc)
    assert len(p.documents) == 1
    assert p.documents[0].doc_type == DocumentType.PETITION_CC1411


def test_all_downstream_complete():
    p = NameChangePetition()
    p.downstream_updates = [
        DownstreamUpdate(agency="SSA", status=DownstreamStatus.COMPLETED),
        DownstreamUpdate(agency="DMV", status=DownstreamStatus.COMPLETED),
    ]
    assert p.all_downstream_complete() is True

    p.downstream_updates.append(
        DownstreamUpdate(agency="Passport", status=DownstreamStatus.PENDING)
    )
    assert p.all_downstream_complete() is False
