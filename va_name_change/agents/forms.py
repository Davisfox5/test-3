"""Forms Agent — generates and populates all required documents.

In production this agent would fill real PDF templates using a library such
as ``pdfrw``, ``PyPDF2``, or a hosted API (DocuSign, Formstack).  The
implementation below produces plain-text renderings that mirror the actual
form fields, making the logic testable without binary PDF dependencies.
"""

from __future__ import annotations

import os
import textwrap
from datetime import datetime
from typing import Optional

from va_name_change.config import config
from va_name_change.models import (
    Document,
    DocumentType,
    NameChangePetition,
    PetitionStatus,
)


def _ensure_output_dir(petition_id: str) -> str:
    path = os.path.join(config.output_dir, petition_id)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Individual form generators
# ---------------------------------------------------------------------------

def _generate_cc1411(p: NameChangePetition, out_dir: str) -> Document:
    """Generate Virginia Form CC-1411 — Petition for Change of Name."""
    assert p.jurisdiction is not None
    assert p.address is not None

    content = textwrap.dedent(f"""\
        VIRGINIA: IN THE CIRCUIT COURT OF {p.jurisdiction.name.upper()}

        PETITION FOR CHANGE OF NAME  (Form CC-1411)
        =============================================

        Case No.: _______________

        1.  Petitioner's present legal name: {p.current_legal_name}
        2.  Desired new name:                {p.desired_name}
        3.  Date of birth:                   {p.dob}
        4.  Reason for name change:          {p.reason}

        5.  Petitioner's address:
            {p.address.street}
            {p.address.city}, {p.address.state} {p.address.zip_code}

        6.  Petitioner has been a bona fide resident of the Commonwealth
            of Virginia and of {p.address.county or p.address.city} for at
            least six months immediately preceding the filing of this petition.

        7.  Petitioner has not been convicted of a felony, or if so,
            more than two years have elapsed since completion of the sentence.

        8.  The name change is not sought for a fraudulent or illegal purpose.

        WHEREFORE, Petitioner respectfully requests that this Court enter
        an Order changing Petitioner's name from
        "{p.current_legal_name}" to "{p.desired_name}".

        ____________________________          Date: ______________
        Petitioner's Signature

        Filed pursuant to Va. Code § 8.01-217
    """)

    filepath = os.path.join(out_dir, "CC-1411_petition.txt")
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)

    return Document(doc_type=DocumentType.PETITION_CC1411, file_path=filepath)


def _generate_cover_letter(p: NameChangePetition, out_dir: str) -> Document:
    """Generate a cover letter addressed to the circuit court clerk."""
    assert p.jurisdiction is not None

    content = textwrap.dedent(f"""\
        {datetime.utcnow().strftime("%B %d, %Y")}

        Clerk of the Circuit Court
        {p.jurisdiction.name}
        {p.jurisdiction.address.street}
        {p.jurisdiction.address.city}, VA {p.jurisdiction.address.zip_code}

        Re: Petition for Change of Name — {p.current_legal_name}

        Dear Clerk:

        Enclosed please find the following documents in support of my
        Petition for Change of Name:

          1. Petition for Change of Name (Form CC-1411)
          2. Filing fee of ${p.jurisdiction.filing_fee_usd:.2f}
             (check / money order payable to the Clerk)
          3. Fingerprint card (to be submitted for background check
             per Va. Code § 8.01-217)

        Please contact me at the address above if any additional
        information is required.

        Respectfully,

        ____________________________
        {p.current_legal_name}
        {p.address.street}
        {p.address.city}, {p.address.state} {p.address.zip_code}
    """)

    filepath = os.path.join(out_dir, "cover_letter.txt")
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)

    return Document(doc_type=DocumentType.COVER_LETTER, file_path=filepath)


def _generate_publication_notice(p: NameChangePetition, out_dir: str) -> Optional[Document]:
    """Generate newspaper publication notice (if required by jurisdiction)."""
    if p.jurisdiction and not p.jurisdiction.publication_required:
        return None

    content = textwrap.dedent(f"""\
        LEGAL NOTICE — PETITION FOR CHANGE OF NAME

        Notice is hereby given that {p.current_legal_name}, residing in
        {p.address.county or p.address.city}, Virginia, has filed a
        Petition in the {p.jurisdiction.name} requesting that the Court
        enter an Order changing the petitioner's name from
        "{p.current_legal_name}" to "{p.desired_name}".

        Any person who objects to the granting of this petition may appear
        and be heard at the hearing scheduled by the Court.

        Filed pursuant to Va. Code § 8.01-217.
    """)

    filepath = os.path.join(out_dir, "publication_notice.txt")
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)

    return Document(doc_type=DocumentType.PUBLICATION_NOTICE, file_path=filepath)


def _generate_ss5(p: NameChangePetition, out_dir: str) -> Document:
    """Generate SSA Form SS-5 (Application for a Social Security Card)."""
    content = textwrap.dedent(f"""\
        SOCIAL SECURITY ADMINISTRATION
        Application for a Social Security Card  (Form SS-5)
        ====================================================

        1.  NAME (as shown on Social Security card):
            {p.current_legal_name}

        2.  NAME TO BE SHOWN ON CARD:
            {p.desired_name}

        3.  DATE OF BIRTH:  {p.dob}

        4.  PLACE OF BIRTH: _______________

        5.  MAILING ADDRESS:
            {p.address.street}
            {p.address.city}, {p.address.state} {p.address.zip_code}

        REQUIRED DOCUMENTS:
          - Certified court order for name change
          - Valid photo ID (driver's license, passport, etc.)

        Signature: ____________________________   Date: ___________

        Mail to your local Social Security office or visit in person.
    """)

    filepath = os.path.join(out_dir, "SS-5_application.txt")
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)

    return Document(doc_type=DocumentType.SSA_SS5, file_path=filepath)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_all_forms(petition: NameChangePetition) -> list[Document]:
    """Generate every required document for *petition*.

    Returns the list of ``Document`` objects (also appended to the
    petition's ``documents`` list).
    """
    out_dir = _ensure_output_dir(petition.petition_id)
    docs: list[Document] = []

    # Court filing documents
    docs.append(_generate_cc1411(petition, out_dir))
    docs.append(_generate_cover_letter(petition, out_dir))

    pub = _generate_publication_notice(petition, out_dir)
    if pub:
        docs.append(pub)

    # Post-decree forms (pre-generated so they're ready when needed)
    docs.append(_generate_ss5(petition, out_dir))

    for doc in docs:
        petition.add_document(doc)

    petition.advance(PetitionStatus.FORMS_READY)
    return docs
