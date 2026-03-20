"""Filing Agent — handles submission of the petition to the circuit court.

Depending on the jurisdiction, filing may be electronic (via the Virginia
OCRA e-filing portal) or physical (print-and-mail / in-person).  This
agent determines the correct path and produces actionable instructions.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Optional

from va_name_change.models import NameChangePetition, PetitionStatus


@dataclass
class FilingInstructions:
    """Structured output from the filing agent."""

    method: str                    # "efiling" | "in_person" | "mail"
    steps: list[str]
    filing_fee: float
    payment_methods: list[str]
    court_name: str
    court_address: str
    court_phone: str
    efiling_url: Optional[str] = None
    fingerprint_info: str = ""
    estimated_timeline: str = ""


def _fingerprint_guidance(petition: NameChangePetition) -> str:
    """Return jurisdiction-appropriate fingerprint instructions."""
    return textwrap.dedent("""\
        Per Va. Code § 8.01-217, a criminal background check is required.
        Steps:
          1. Obtain a fingerprint card from your local police department
             or an approved Live Scan provider.
          2. Have your fingerprints taken (fee varies, typically $10-$15).
          3. Submit the card to the circuit court clerk with your petition.
          4. The clerk will forward it to the Virginia State Police for
             processing (additional fee may apply).
    """).strip()


def get_filing_instructions(petition: NameChangePetition) -> FilingInstructions:
    """Build filing instructions without changing petition status."""
    court = petition.jurisdiction
    assert court is not None

    fingerprint_info = _fingerprint_guidance(petition)

    if court.accepts_efiling:
        return FilingInstructions(
            method="efiling",
            steps=[
                f"Navigate to the Virginia OCRA e-filing portal for {court.name}.",
                "Create an account or log in.",
                "Select 'Civil — Petition for Change of Name'.",
                "Upload the completed CC-1411 petition PDF.",
                f"Pay the filing fee of ${court.filing_fee_usd:.2f} via credit card.",
                "Upload or schedule fingerprint submission as instructed by the portal.",
                "Save your confirmation number for tracking.",
            ],
            filing_fee=court.filing_fee_usd,
            payment_methods=["credit_card", "debit_card"],
            court_name=court.name,
            court_address=(
                f"{court.address.street}, {court.address.city}, "
                f"VA {court.address.zip_code}"
            ),
            court_phone=court.phone,
            efiling_url=court.local_rules_url,
            fingerprint_info=fingerprint_info,
            estimated_timeline="Typically 4-8 weeks from filing to hearing.",
        )
    else:
        return FilingInstructions(
            method="in_person",
            steps=[
                f"Print all documents from your output folder.",
                "Obtain a fingerprint card from your local police department.",
                f"Visit the {court.name} clerk's office at:",
                f"  {court.address.street}, {court.address.city}, VA {court.address.zip_code}",
                f"  Phone: {court.phone}",
                f"Submit the petition (CC-1411), cover letter, and fingerprint card.",
                f"Pay the filing fee of ${court.filing_fee_usd:.2f}.",
                "Request a hearing date from the clerk.",
                "Ask the clerk about publication requirements for your jurisdiction.",
            ],
            filing_fee=court.filing_fee_usd,
            payment_methods=["check", "money_order", "cash"],
            court_name=court.name,
            court_address=(
                f"{court.address.street}, {court.address.city}, "
                f"VA {court.address.zip_code}"
            ),
            court_phone=court.phone,
            fingerprint_info=fingerprint_info,
            estimated_timeline="Typically 6-12 weeks from filing to hearing.",
        )


def prepare_filing(petition: NameChangePetition) -> FilingInstructions:
    """Build filing instructions and advance petition status to FILED."""
    instructions = get_filing_instructions(petition)
    petition.advance(PetitionStatus.FILED)
    return instructions


def format_instructions(fi: FilingInstructions) -> str:
    """Return a human-readable summary of filing instructions."""
    lines = [
        f"=== Filing Instructions ({fi.method.upper()}) ===",
        f"Court: {fi.court_name}",
        f"Address: {fi.court_address}",
        f"Phone: {fi.court_phone}",
        f"Filing fee: ${fi.filing_fee:.2f}",
        f"Payment methods: {', '.join(fi.payment_methods)}",
        "",
        "Steps:",
    ]
    for i, step in enumerate(fi.steps, 1):
        lines.append(f"  {i}. {step}")

    lines += [
        "",
        "Fingerprint / Background Check:",
        fi.fingerprint_info,
        "",
        f"Estimated timeline: {fi.estimated_timeline}",
    ]
    return "\n".join(lines)
