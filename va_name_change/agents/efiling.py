"""E-Filing Agent — submits petitions electronically to VJEFS-participating courts.

This agent handles the complete electronic filing workflow:
1. Creates an envelope in VJEFS for the court
2. Uploads all generated documents (CC-1411, cover letter, etc.)
3. Processes the filing fee payment
4. Submits the filing to the court
5. Polls for acceptance and retrieves case number / hearing date
6. Advances petition status automatically

For courts that don't accept e-filing, falls back to generating
print-and-mail instructions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from va_name_change.models import (
    DocumentType,
    NameChangePetition,
    PetitionStatus,
)
from va_name_change.services.vjefs_client import (
    EFilingStatus,
    EFilingSubmission,
    VJEFSError,
    get_vjefs_client,
)

logger = logging.getLogger(__name__)


# Map our DocumentType to VJEFS document categories
_DOC_TYPE_MAP: dict[DocumentType, str] = {
    DocumentType.PETITION_CC1411: "PETITION",
    DocumentType.COVER_LETTER: "COVER_LETTER",
    DocumentType.PUBLICATION_NOTICE: "PUBLICATION_NOTICE",
    DocumentType.FINGERPRINT_CARD: "FINGERPRINT_CARD",
    DocumentType.SSA_SS5: "SUPPORTING_DOCUMENT",
}


@dataclass
class EFilingResult:
    """Result of an e-filing attempt."""
    success: bool
    submission: EFilingSubmission
    method: str                        # "efiled" | "manual_required"
    message: str = ""
    error: Optional[str] = None


def can_efile(petition: NameChangePetition) -> bool:
    """Check if this petition's jurisdiction supports e-filing."""
    return (
        petition.jurisdiction is not None
        and petition.jurisdiction.accepts_efiling
    )


def submit_efiling(petition: NameChangePetition) -> EFilingResult:
    """Submit the petition electronically via VJEFS.

    This is the main entry point. It:
    1. Checks e-filing eligibility
    2. Creates a VJEFS envelope
    3. Uploads all documents
    4. Pays the filing fee
    5. Submits to the court
    6. Polls for acceptance
    7. Updates the petition with case number and hearing date

    Returns an EFilingResult with status details.
    """
    submission = EFilingSubmission(petition_id=petition.petition_id)

    if not can_efile(petition):
        submission.status = EFilingStatus.FAILED
        return EFilingResult(
            success=False,
            submission=submission,
            method="manual_required",
            message=(
                f"{petition.jurisdiction.name} does not accept e-filing. "
                "Please file in person or by mail."
            ),
        )

    court = petition.jurisdiction
    submission.court_fips = court.fips_code

    client = get_vjefs_client()

    try:
        # Step 1: Create envelope
        logger.info("Creating VJEFS envelope for court FIPS %s", court.fips_code)
        env_resp = client.create_envelope(court.fips_code, case_type="NAME_CHANGE")
        submission.envelope_id = env_resp["envelope_id"]
        submission.status = EFilingStatus.SUBMITTED

        # Step 2: Upload all generated documents
        for doc in petition.documents:
            vjefs_type = _DOC_TYPE_MAP.get(doc.doc_type, "SUPPORTING_DOCUMENT")
            logger.info("Uploading %s (%s)", doc.doc_type.value, doc.file_path)
            client.upload_document(submission.envelope_id, doc.file_path, vjefs_type)
            submission.documents_uploaded.append(doc.file_path)

        # Step 3: Pay filing fee
        fee = court.filing_fee_usd
        logger.info("Processing filing fee: $%.2f", fee)
        pay_resp = client.submit_payment(submission.envelope_id, fee)
        submission.filing_fee_paid = fee
        submission.payment_transaction_id = pay_resp.get("transaction_id")
        submission.status = EFilingStatus.PAYMENT_COMPLETE

        # Step 4: Submit the filing
        logger.info("Submitting filing to %s", court.name)
        submit_resp = client.submit_filing(submission.envelope_id)
        submission.confirmation_code = submit_resp.get("confirmation_code")
        submission.case_number = submit_resp.get("case_number")
        submission.submitted_at = datetime.utcnow()
        submission.status = EFilingStatus.SUBMITTED

        # Step 5: Poll for acceptance
        status_resp = client.get_filing_status(submission.envelope_id)
        if status_resp.get("status") == "ACCEPTED":
            submission.status = EFilingStatus.ACCEPTED
            submission.accepted_at = datetime.utcnow()

            # Extract case details
            case_resp = client.get_case_details(submission.envelope_id)
            submission.case_number = case_resp.get("case_number", submission.case_number)
            hearing_str = case_resp.get("hearing_date")
            if hearing_str:
                submission.hearing_date = date.fromisoformat(hearing_str)

        elif status_resp.get("status") == "REJECTED":
            submission.status = EFilingStatus.REJECTED
            submission.rejected_reason = status_resp.get("reason", "Unknown")
            return EFilingResult(
                success=False,
                submission=submission,
                method="efiled",
                message="Filing was rejected by the court.",
                error=submission.rejected_reason,
            )

        # Step 6: Update petition status
        if petition.status == PetitionStatus.FORMS_READY:
            petition.advance(PetitionStatus.FILED)

        if submission.hearing_date:
            petition.hearing_date = submission.hearing_date
            if petition.status == PetitionStatus.FILED:
                petition.advance(PetitionStatus.HEARING_SCHEDULED)

        logger.info(
            "E-filing complete: case %s, hearing %s, confirmation %s",
            submission.case_number,
            submission.hearing_date,
            submission.confirmation_code,
        )

        return EFilingResult(
            success=True,
            submission=submission,
            method="efiled",
            message=(
                f"Successfully e-filed with {court.name}. "
                f"Case number: {submission.case_number}. "
                f"Confirmation: {submission.confirmation_code}."
                + (
                    f" Hearing date: {submission.hearing_date.strftime('%B %d, %Y')}."
                    if submission.hearing_date else ""
                )
            ),
        )

    except VJEFSError as exc:
        logger.error("VJEFS error during e-filing: %s", exc)
        submission.status = EFilingStatus.FAILED
        return EFilingResult(
            success=False,
            submission=submission,
            method="efiled",
            message="E-filing failed due to a system error.",
            error=str(exc),
        )


def poll_filing_status(submission: EFilingSubmission,
                       petition: NameChangePetition) -> EFilingSubmission:
    """Re-check the status of an existing submission.

    Call this periodically for filings that are still SUBMITTED
    (not yet ACCEPTED).
    """
    if not submission.envelope_id:
        return submission

    client = get_vjefs_client()

    try:
        resp = client.get_filing_status(submission.envelope_id)
        status = resp.get("status", "")

        if status == "ACCEPTED" and submission.status != EFilingStatus.ACCEPTED:
            submission.status = EFilingStatus.ACCEPTED
            submission.accepted_at = datetime.utcnow()

            case_resp = client.get_case_details(submission.envelope_id)
            submission.case_number = case_resp.get("case_number", submission.case_number)
            hearing_str = case_resp.get("hearing_date")
            if hearing_str:
                submission.hearing_date = date.fromisoformat(hearing_str)

            # Auto-advance petition
            if petition.status == PetitionStatus.FILED and submission.hearing_date:
                petition.hearing_date = submission.hearing_date
                petition.advance(PetitionStatus.HEARING_SCHEDULED)

        elif status == "REJECTED":
            submission.status = EFilingStatus.REJECTED
            submission.rejected_reason = resp.get("reason", "Unknown")

    except VJEFSError as exc:
        logger.warning("Failed to poll filing status: %s", exc)

    return submission
