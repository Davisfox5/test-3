"""Core data models for the Virginia name-change pipeline."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PetitionStatus(enum.Enum):
    """High-level lifecycle of a name-change petition."""

    INTAKE = "intake"
    FORMS_READY = "forms_ready"
    FILED = "filed"
    HEARING_SCHEDULED = "hearing_scheduled"
    GRANTED = "granted"
    POST_DECREE_IN_PROGRESS = "post_decree_in_progress"
    COMPLETED = "completed"
    DENIED = "denied"


class DownstreamStatus(enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentType(enum.Enum):
    PETITION_CC1411 = "CC-1411"
    ORDER_OF_NAME_CHANGE = "order_of_name_change"
    FINGERPRINT_CARD = "fingerprint_card"
    PUBLICATION_NOTICE = "publication_notice"
    SSA_SS5 = "SS-5"
    PASSPORT_DS11 = "DS-11"
    PASSPORT_DS5504 = "DS-5504"
    VA_DMV_DL_APPLICATION = "va_dmv_dl_app"
    BIRTH_CERT_AMENDMENT = "birth_cert_amendment"
    COVER_LETTER = "cover_letter"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass
class Address:
    street: str
    city: str
    state: str = "VA"
    zip_code: str = ""
    county: str = ""


@dataclass
class CircuitCourt:
    name: str
    fips_code: str
    address: Address
    phone: str = ""
    filing_fee_usd: float = 0.0
    accepts_efiling: bool = False
    local_rules_url: str = ""
    publication_required: bool = True


@dataclass
class Document:
    doc_type: DocumentType
    file_path: str
    generated_at: datetime = field(default_factory=datetime.utcnow)
    signed: bool = False


@dataclass
class DownstreamUpdate:
    """A single post-decree update (SSA, DMV, etc.)."""

    agency: str
    form_type: Optional[DocumentType] = None
    status: DownstreamStatus = DownstreamStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Aggregate root
# ---------------------------------------------------------------------------

@dataclass
class NameChangePetition:
    """Central aggregate that tracks the entire name-change process."""

    petition_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    current_legal_name: str = ""
    desired_name: str = ""
    reason: str = ""
    dob: Optional[date] = None
    place_of_birth: str = ""
    ssn_encrypted: str = ""          # stored encrypted; never logged
    address: Optional[Address] = None
    jurisdiction: Optional[CircuitCourt] = None
    status: PetitionStatus = PetitionStatus.INTAKE
    documents: list[Document] = field(default_factory=list)
    downstream_updates: list[DownstreamUpdate] = field(default_factory=list)
    hearing_date: Optional[date] = None
    case_number: Optional[str] = None          # assigned by court after filing
    efiling_confirmation: Optional[str] = None  # VJEFS confirmation code
    efiling_envelope_id: Optional[str] = None   # VJEFS envelope tracking ID
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # -- convenience helpers --------------------------------------------------

    def advance(self, new_status: PetitionStatus) -> None:
        self.status = new_status
        self.updated_at = datetime.utcnow()

    def add_document(self, doc: Document) -> None:
        self.documents.append(doc)
        self.updated_at = datetime.utcnow()

    def all_downstream_complete(self) -> bool:
        return all(
            u.status == DownstreamStatus.COMPLETED
            for u in self.downstream_updates
        )
