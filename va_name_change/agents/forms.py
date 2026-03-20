"""Forms Agent — fills the official VA CC-1411 PDF and generates supporting docs.

Uses pdfrw to fill the real Virginia Circuit Court CC-1411 form and
reportlab to produce a cover letter and SS-5 reproduction.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import PyPDF2
from pdfrw import PdfReader, PdfWriter, PdfDict, PdfName, PdfString
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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
# CC-1411: fill the real Virginia court form
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "form_templates")


def _split_name(full_name: str) -> tuple[str, str, str, str]:
    """Split a full name into (first, middle, last, suffix).

    Handles common suffixes like Jr, Sr, II, III, IV.
    """
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v", "esq", "esq."}
    parts = full_name.strip().split()
    suffix = ""
    if len(parts) > 1 and parts[-1].lower().rstrip(".") in {s.rstrip(".") for s in suffixes}:
        suffix = parts.pop()

    if len(parts) == 0:
        return ("", "", "", suffix)
    elif len(parts) == 1:
        return (parts[0], "", "", suffix)
    elif len(parts) == 2:
        return (parts[0], "", parts[1], suffix)
    else:
        return (parts[0], " ".join(parts[1:-1]), parts[-1], suffix)


def _encode(text: str) -> PdfString:
    """Encode a string as a PDF text value."""
    return PdfString.from_bytes(text.encode("latin-1", errors="replace"))


def _fill_text_field(annots, field_name: str, value: str) -> None:
    """Set a text field value across all annotations."""
    for annot in annots:
        t = annot["/T"]
        if t and str(t).strip("()") == field_name:
            annot.update(PdfDict(V=_encode(value), AP=""))


def _fill_radio(annots, parent_name: str, choice: str) -> None:
    """Set a radio button group to a specific choice value (e.g. '/1')."""
    for annot in annots:
        parent = annot["/Parent"]
        if parent and str(parent["/T"]).strip("()") == parent_name:
            ap = annot["/AP"]
            if ap and ap["/N"]:
                keys = list(ap["/N"].keys())
                if choice in keys:
                    annot.update(PdfDict(AS=PdfName(choice.lstrip("/"))))
                else:
                    annot.update(PdfDict(AS=PdfName("Off")))


def _generate_cc1411(p: NameChangePetition, out_dir: str) -> Document:
    """Fill the official Virginia CC-1411 form with petition data."""
    assert p.jurisdiction is not None
    assert p.address is not None

    template_path = os.path.join(_TEMPLATE_DIR, "cc1411.pdf")
    reader = PdfReader(template_path)

    # Split names
    cur_first, cur_mid, cur_last, cur_suffix = _split_name(p.current_legal_name)
    des_first, des_mid, des_last, des_suffix = _split_name(p.desired_name)

    # Collect all annotations across pages
    all_annots = []
    for page in reader.pages:
        annots = page["/Annots"]
        if annots:
            all_annots.extend(annots)

    # Court name
    _fill_text_field(all_annots, "Court", p.jurisdiction.name)

    # "In Re" — petitioner's current name
    _fill_text_field(all_annots, "InReFirstName", cur_first)
    _fill_text_field(all_annots, "InReMiddleName", cur_mid)
    _fill_text_field(all_annots, "InReLastName", cur_last)
    _fill_text_field(all_annots, "InReSuffix", cur_suffix)

    # Petitioner info
    _fill_text_field(all_annots, "PetitionerFirstName", cur_first)
    _fill_text_field(all_annots, "PetitionerMiddleName", cur_mid)
    _fill_text_field(all_annots, "PetitionerLastName", cur_last)
    _fill_text_field(all_annots, "PetitionerSuffix", cur_suffix)

    # Address
    _fill_text_field(all_annots, "CountyOfResidence", p.address.county or p.address.city)
    _fill_text_field(all_annots, "PetitionerAddress", p.address.street)
    _fill_text_field(all_annots, "PetitionerCity", p.address.city)
    _fill_text_field(all_annots, "PetitionerState", p.address.state)
    _fill_text_field(all_annots, "PetitionerZip", p.address.zip_code)
    _fill_text_field(all_annots, "PetitionerCountry\\", "USA")

    # DOB and place of birth
    dob_str = p.dob.strftime("%m/%d/%Y") if p.dob else ""
    _fill_text_field(all_annots, "PetitionerDOB", dob_str)
    _fill_text_field(all_annots, "PetitionerPlaceOfBirtg", p.place_of_birth)

    # Reason for name change
    _fill_text_field(all_annots, "ChangeA", p.reason)

    # Page 2: From / To names
    _fill_text_field(all_annots, "FromFirstName", cur_first)
    _fill_text_field(all_annots, "FromMiddleName", cur_mid)
    _fill_text_field(all_annots, "FromLastName", cur_last)
    _fill_text_field(all_annots, "FromSuffix", cur_suffix)
    _fill_text_field(all_annots, "ToFirstName", des_first)
    _fill_text_field(all_annots, "ToMiddleName", des_mid)
    _fill_text_field(all_annots, "ToLastName", des_last)
    _fill_text_field(all_annots, "ToSuffix", des_suffix)

    # Court type: Circuit Court = /1
    _fill_radio(all_annots, "CourtCB", "/1")

    # Yes/No questions — default to "No" (/2) for criminal/sex-offender questions
    # YNCB1-5: /1 = Yes, /2 = No, /0 = N/A
    _fill_radio(all_annots, "YNCB1", "/2")  # Convicted of a felony?
    _fill_radio(all_annots, "YNCB2", "/2")  # Currently incarcerated?
    _fill_radio(all_annots, "YNCB3", "/2")  # Previous name change denied?
    _fill_radio(all_annots, "YNCB4", "/2")  # Registered sex offender?
    _fill_radio(all_annots, "YNCB5", "/2")  # Other names used?

    # Flatten appearance so values show in non-editor viewers
    reader.Root.AcroForm.update(
        PdfDict(NeedAppearances=PdfName("true"))
    )

    filepath = os.path.join(out_dir, "CC-1411_petition.pdf")
    writer = PdfWriter(filepath)
    writer.addpages(reader.pages)
    writer.trailer = reader
    writer.write()

    return Document(doc_type=DocumentType.PETITION_CC1411, file_path=filepath)


# ---------------------------------------------------------------------------
# Reportlab-based PDF helpers (for cover letter and SS-5)
# ---------------------------------------------------------------------------

_styles = getSampleStyleSheet()

_TITLE_STYLE = ParagraphStyle("FormTitle", parent=_styles["Title"], fontSize=14, spaceAfter=12)
_HEADING_STYLE = ParagraphStyle("FormHeading", parent=_styles["Heading2"], fontSize=12, spaceAfter=6)
_BODY_STYLE = ParagraphStyle("FormBody", parent=_styles["Normal"], fontSize=11, leading=15, spaceAfter=6)
_SMALL_STYLE = ParagraphStyle("FormSmall", parent=_styles["Normal"], fontSize=9, leading=12, spaceAfter=4)
_SIG_STYLE = ParagraphStyle("FormSig", parent=_styles["Normal"], fontSize=11, leading=15, spaceBefore=24)


def _build_pdf(filepath: str, story: list) -> None:
    doc = SimpleDocTemplate(filepath, pagesize=letter,
                            leftMargin=1*inch, rightMargin=1*inch,
                            topMargin=1*inch, bottomMargin=1*inch)
    doc.build(story)


def _sig_block(name: str, address_lines: list[str]) -> list:
    elements = [
        Spacer(1, 24),
        Paragraph("____________________________&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Date: ______________", _SIG_STYLE),
        Paragraph(name, _SMALL_STYLE),
    ]
    for line in address_lines:
        elements.append(Paragraph(line, _SMALL_STYLE))
    return elements


# ---------------------------------------------------------------------------
# Cover letter
# ---------------------------------------------------------------------------

def _generate_cover_letter(p: NameChangePetition, out_dir: str) -> Document:
    """Generate a cover letter addressed to the circuit court clerk (PDF)."""
    assert p.jurisdiction is not None

    filepath = os.path.join(out_dir, "cover_letter.pdf")
    story = [
        Paragraph(datetime.utcnow().strftime("%B %d, %Y"), _BODY_STYLE),
        Spacer(1, 12),
        Paragraph("Clerk of the Circuit Court", _BODY_STYLE),
        Paragraph(p.jurisdiction.name, _BODY_STYLE),
        Paragraph(p.jurisdiction.address.street, _BODY_STYLE),
        Paragraph(f"{p.jurisdiction.address.city}, VA {p.jurisdiction.address.zip_code}", _BODY_STYLE),
        Spacer(1, 12),
        Paragraph(f"<b>Re: Petition for Change of Name — {p.current_legal_name}</b>", _BODY_STYLE),
        Spacer(1, 6),
        Paragraph("Dear Clerk:", _BODY_STYLE),
        Spacer(1, 6),
        Paragraph(
            "Enclosed please find the following documents in support of my "
            "Petition for Change of Name:", _BODY_STYLE),
        Spacer(1, 6),
        Paragraph("&nbsp;&nbsp;1. Petition for Change of Name (Form CC-1411)", _BODY_STYLE),
        Paragraph(
            f"&nbsp;&nbsp;2. Filing fee of ${p.jurisdiction.filing_fee_usd:.2f} "
            f"(check / money order payable to the Clerk)", _BODY_STYLE),
        Paragraph(
            "&nbsp;&nbsp;3. Fingerprint card (to be submitted for background check "
            "per Va. Code &sect; 8.01-217)", _BODY_STYLE),
        Spacer(1, 6),
        Paragraph(
            "Please contact me at the address above if any additional "
            "information is required.", _BODY_STYLE),
        Paragraph("Respectfully,", _BODY_STYLE),
    ]
    story.extend(_sig_block(p.current_legal_name, [
        p.address.street,
        f"{p.address.city}, {p.address.state} {p.address.zip_code}",
    ]))
    _build_pdf(filepath, story)
    return Document(doc_type=DocumentType.COVER_LETTER, file_path=filepath)


# ---------------------------------------------------------------------------
# Publication notice
# ---------------------------------------------------------------------------

def _generate_publication_notice(p: NameChangePetition, out_dir: str) -> Optional[Document]:
    """Generate newspaper publication notice (PDF, if required)."""
    if p.jurisdiction and not p.jurisdiction.publication_required:
        return None

    filepath = os.path.join(out_dir, "publication_notice.pdf")
    story = [
        Paragraph("LEGAL NOTICE — PETITION FOR CHANGE OF NAME", _TITLE_STYLE),
        Spacer(1, 12),
        Paragraph(
            f"Notice is hereby given that {p.current_legal_name}, residing in "
            f"{p.address.county or p.address.city}, Virginia, has filed a "
            f"Petition in the {p.jurisdiction.name} requesting that the Court "
            f"enter an Order changing the petitioner's name from "
            f'"{p.current_legal_name}" to "{p.desired_name}".', _BODY_STYLE),
        Spacer(1, 6),
        Paragraph(
            "Any person who objects to the granting of this petition may appear "
            "and be heard at the hearing scheduled by the Court.", _BODY_STYLE),
        Spacer(1, 12),
        Paragraph("Filed pursuant to Va. Code &sect; 8.01-217.", _SMALL_STYLE),
    ]
    _build_pdf(filepath, story)
    return Document(doc_type=DocumentType.PUBLICATION_NOTICE, file_path=filepath)


# ---------------------------------------------------------------------------
# SS-5: fill the official SSA form
# ---------------------------------------------------------------------------

_SS5_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms", "ss-5.pdf"
)


def _generate_ss5(p: NameChangePetition, out_dir: str) -> Document:
    """Fill the official SSA SS-5 form with petition data."""
    cur_first, cur_mid, cur_last, _ = _split_name(p.current_legal_name)
    des_first, des_mid, des_last, _ = _split_name(p.desired_name)

    # Split place of birth into city and state
    pob_parts = [x.strip() for x in p.place_of_birth.split(",", 1)]
    pob_city = pob_parts[0] if pob_parts else ""
    pob_state = pob_parts[1] if len(pob_parts) > 1 else ""

    dob_str = p.dob.strftime("%m/%d/%Y") if p.dob else ""

    field_values = {
        # Section 1: Name to show on card (the NEW name)
        "P5_firstname_FLD[0]": des_first,
        "P5_Middlename_FLD[0]": des_mid,
        "P5_LastName_FLD[0]": des_last,
        # Section 2: Different name (previous/current name)
        "P5_firstdiffname_FLD[0]": cur_first,
        "P5_Middlediffname_FLD[0]": cur_mid,
        "P5_Lastdiffname_FLD[0]": cur_last,
        # Section 3: Place of birth
        "P5_cityofbirth_FLD[0]": pob_city,
        "P5_stateatbirth_FLD[0]": pob_state,
        # Section 4: Date of birth
        "P5_4dateofbirth_Date[0]": dob_str,
        # Section 5: Citizenship — US citizen
        "P5_UScit_CB1[0]": True,
        # Section 12: Name on most recent card (current/old name)
        "P5_firstnameonrecentcard_FLD[0]": cur_first,
        "P5_middlenameonrecentcard_FLD[0]": cur_mid,
        "P5_lastnameonrecentcard_FLD[0]": cur_last,
        # Section 13: Today's date
        "P5_13date_Date[0]": datetime.utcnow().strftime("%m/%d/%Y"),
        # Section 16: Mailing address
        "P5_streetaddress_FLD[0]": p.address.street,
        "P5_mailingcity_FLD[0]": p.address.city,
        "P5_state_FLD[0]": p.address.state,
        "P5_zipcode_FLD[0]": p.address.zip_code,
        # Section 18: Relationship — self
        "P5_Self_CB21[0]": True,
    }

    reader = PyPDF2.PdfReader(_SS5_TEMPLATE)
    writer = PyPDF2.PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    # Copy over the AcroForm from the reader
    if "/AcroForm" in reader.trailer["/Root"]:
        writer._root_object[PyPDF2.generic.NameObject("/AcroForm")] = reader.trailer["/Root"]["/AcroForm"]

    # Fill fields
    for page_num in range(len(writer.pages)):
        page = writer.pages[page_num]
        annots = page.get("/Annots")
        if not annots:
            continue
        for annot in annots:
            annot_obj = annot.get_object()
            field_name = annot_obj.get("/T")
            if field_name and str(field_name) in field_values:
                value = field_values[str(field_name)]
                if isinstance(value, bool) and value:
                    # Check the checkbox
                    annot_obj.update({
                        PyPDF2.generic.NameObject("/V"): PyPDF2.generic.NameObject("/Yes"),
                        PyPDF2.generic.NameObject("/AS"): PyPDF2.generic.NameObject("/Yes"),
                    })
                elif isinstance(value, str):
                    annot_obj.update({
                        PyPDF2.generic.NameObject("/V"): PyPDF2.generic.create_string_object(value),
                    })

    # Set NeedAppearances so readers regenerate field visuals
    if "/AcroForm" in writer._root_object:
        writer._root_object["/AcroForm"].update({
            PyPDF2.generic.NameObject("/NeedAppearances"): PyPDF2.generic.BooleanObject(True),
        })

    filepath = os.path.join(out_dir, "SS-5_application.pdf")
    with open(filepath, "wb") as f:
        writer.write(f)

    return Document(doc_type=DocumentType.SSA_SS5, file_path=filepath)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_all_forms(petition: NameChangePetition) -> list[Document]:
    """Generate every required document for *petition*.

    - CC-1411: filled from the official Virginia court PDF template
    - Cover letter, publication notice, SS-5: generated as PDFs
    """
    out_dir = _ensure_output_dir(petition.petition_id)
    docs: list[Document] = []

    docs.append(_generate_cc1411(petition, out_dir))
    docs.append(_generate_cover_letter(petition, out_dir))

    pub = _generate_publication_notice(petition, out_dir)
    if pub:
        docs.append(pub)

    docs.append(_generate_ss5(petition, out_dir))

    for doc in docs:
        petition.add_document(doc)

    petition.advance(PetitionStatus.FORMS_READY)
    return docs
