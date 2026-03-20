"""Filing Agent — produces step-by-step instructions for filing the petition.

Virginia circuit courts require name change petitions (CC-1411) to be filed
in person or by mail.  The application must be signed under oath before a
notary public or a deputy clerk (Va. Code § 8.01-217).

There is no public API or self-service e-filing option for pro se name
change petitions:
  - VJEFS (Virginia Judiciary eFiling System) is restricted to licensed
    Virginia attorneys and their staff.
  - eFileVA (Tyler/Odyssey) supports some courts and case types but
    name change availability varies by jurisdiction and still requires
    the oath/notarization step.

This agent generates accurate, court-specific filing instructions for
in-person or mail submission.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Optional

from va_name_change.models import NameChangePetition, PetitionStatus


@dataclass
class FilingInstructions:
    """Structured output from the filing agent."""

    method: str                    # "in_person" | "mail"
    steps: list[str]
    filing_fee: float
    payment_methods: list[str]
    court_name: str
    court_address: str
    court_phone: str
    oath_info: str = ""
    publication_info: str = ""
    background_check_info: str = ""
    estimated_timeline: str = ""
    local_rules_url: str = ""


def _oath_guidance() -> str:
    """Guidance on the oath/notarization requirement."""
    return textwrap.dedent("""\
        Per Va. Code § 8.01-217, the application must be made under oath.
        You must sign the CC-1411 petition in the presence of either:
          - A notary public (before visiting the court), OR
          - A deputy clerk at the circuit court clerk's office.
        Do NOT sign the petition until you are before the notary or clerk.
    """).strip()


def _publication_guidance(petition: NameChangePetition) -> str:
    """Guidance on the newspaper publication requirement."""
    court = petition.jurisdiction
    if court and not court.publication_required:
        return "Publication is not required by this jurisdiction."

    county = petition.address.county or petition.address.city if petition.address else "your locality"
    return textwrap.dedent(f"""\
        Virginia typically requires notice of the name change to be published
        in a newspaper of general circulation in {county} once a week for a
        period set by local rules (often 1-4 weeks). The court clerk can tell
        you which newspapers are accepted and the required publication period.
        You may request the court to waive publication if you can demonstrate
        a serious threat to your health or safety (Va. Code § 8.01-217(G)).
    """).strip()


def _background_check_guidance() -> str:
    """Guidance on criminal history disclosure (NOT fingerprinting).

    Va. Code § 8.01-217 does NOT require fingerprinting.  The statute
    requires the applicant to self-disclose their felony conviction record,
    sex offender registry status, and incarceration/probation status under
    oath.  Some individual courts may have local practices that differ.
    """
    return textwrap.dedent("""\
        The CC-1411 petition requires you to disclose under oath:
          - Any felony conviction record
          - Whether you are required to register with the Sex Offender
            and Crimes Against Minors Registry
          - Whether you are currently incarcerated or on probation
          - Any previous name changes
        Note: Va. Code § 8.01-217 does not require fingerprinting.
        Some courts may have additional local requirements — check with
        your clerk's office.
    """).strip()


def get_filing_instructions(petition: NameChangePetition) -> FilingInstructions:
    """Build filing instructions without changing petition status.

    All name change petitions are filed in person or by mail.
    """
    court = petition.jurisdiction
    assert court is not None

    oath_info = _oath_guidance()
    publication_info = _publication_guidance(petition)
    background_info = _background_check_guidance()

    return FilingInstructions(
        method="in_person",
        steps=[
            "Print all generated documents from your output folder.",
            "Make two photocopies of the completed CC-1411 petition.",
            "Do NOT sign the petition yet — it must be signed under oath.",
            (
                f"Visit the {court.name} clerk's office at: "
                f"{court.address.street}, {court.address.city}, VA {court.address.zip_code}"
            ),
            (
                "Sign the petition under oath before a deputy clerk, or bring "
                "a copy already notarized by a notary public."
            ),
            "Submit the petition (CC-1411), cover letter, and photocopies.",
            f"Pay the filing fee of ${court.filing_fee_usd:.2f}.",
            "Ask the clerk about newspaper publication requirements.",
            (
                "The clerk will inform you whether a hearing is needed. "
                "Many Virginia courts grant uncontested name changes without "
                "a hearing."
            ),
        ],
        filing_fee=court.filing_fee_usd,
        payment_methods=["check", "money_order", "cash", "credit_card"],
        court_name=court.name,
        court_address=(
            f"{court.address.street}, {court.address.city}, "
            f"VA {court.address.zip_code}"
        ),
        court_phone=court.phone,
        oath_info=oath_info,
        publication_info=publication_info,
        background_check_info=background_info,
        estimated_timeline=(
            "Varies by court. Many uncontested name changes are granted "
            "within 2-8 weeks. Courts that require publication or a hearing "
            "may take longer."
        ),
        local_rules_url=court.local_rules_url,
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
        "Oath / Notarization Requirement:",
        fi.oath_info,
        "",
        "Publication Requirement:",
        fi.publication_info,
        "",
        "Criminal History Disclosure:",
        fi.background_check_info,
        "",
        f"Estimated timeline: {fi.estimated_timeline}",
    ]
    if fi.local_rules_url:
        lines.append(f"Local rules: {fi.local_rules_url}")
    return "\n".join(lines)
