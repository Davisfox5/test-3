"""Intake Agent — collects and validates petitioner information.

This agent drives a structured interview, validating each field before
moving on.  In a real deployment the ``collect_*`` helpers would be wired
to a chat UI or voice interface; here we model them as callable hooks so
the orchestrator can supply any frontend.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Callable, Optional

from va_name_change.models import (
    Address,
    DownstreamUpdate,
    NameChangePetition,
    PetitionStatus,
)
from va_name_change.utils.crypto import encrypt
from va_name_change.utils.jurisdiction import resolve_jurisdiction

# Type alias for the function the orchestrator supplies to ask the user
# a question and return the answer string.
AskFn = Callable[[str], str]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_SSN_RE = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def _validate_ssn(raw: str) -> str:
    """Return a normalised SSN (digits only) or raise."""
    raw = raw.strip()
    if not _SSN_RE.match(raw):
        raise ValueError("SSN must be in the format 123-45-6789 or 123456789.")
    return raw.replace("-", "")


def _validate_date(raw: str) -> date:
    """Parse MM/DD/YYYY or YYYY-MM-DD into a ``date``."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("Date must be MM/DD/YYYY or YYYY-MM-DD.")


def _validate_zip(raw: str) -> str:
    raw = raw.strip()
    if not _ZIP_RE.match(raw):
        raise ValueError("ZIP code must be 5 digits (optionally with +4).")
    return raw


# ---------------------------------------------------------------------------
# Core intake flow
# ---------------------------------------------------------------------------

_DEFAULT_DOWNSTREAM = [
    DownstreamUpdate(agency="SSA", notes="Must be updated first"),
    DownstreamUpdate(agency="VA DMV", depends_on=["SSA"]),
    DownstreamUpdate(agency="US Passport", depends_on=["SSA"]),
    DownstreamUpdate(agency="Birth Certificate", depends_on=["SSA"]),
    DownstreamUpdate(agency="Voter Registration", depends_on=["VA DMV"]),
    DownstreamUpdate(agency="Banks / Financial", depends_on=["SSA"]),
    DownstreamUpdate(agency="Employer / HR", depends_on=["SSA"]),
    DownstreamUpdate(agency="Utilities", depends_on=[]),
    DownstreamUpdate(agency="Professional Licenses", depends_on=["SSA"]),
]


def _ask_validated(ask: AskFn, prompt: str, validator: Callable[[str], object],
                   retries: int = 3) -> object:
    """Ask a question, validate the response, retry on failure."""
    for attempt in range(retries):
        answer = ask(prompt)
        try:
            return validator(answer)
        except (ValueError, TypeError) as exc:
            if attempt < retries - 1:
                ask(f"Invalid input: {exc}  Please try again.")
            else:
                raise
    raise RuntimeError("Max retries exceeded during intake.")  # pragma: no cover


def run_intake(ask: AskFn, petition: Optional[NameChangePetition] = None) -> NameChangePetition:
    """Run the full intake interview and return a populated petition.

    Parameters
    ----------
    ask:
        A callable ``(prompt: str) -> str`` the agent uses to interact with
        the petitioner.  The orchestrator wires this to whatever frontend
        is in use (CLI, web chat, voice, etc.).
    petition:
        An optional existing petition to resume.  If *None* a new one is
        created.
    """
    p = petition or NameChangePetition()

    # -- identity -----------------------------------------------------------
    p.current_legal_name = ask(
        "What is your current full legal name (as it appears on your ID)?"
    ).strip()

    p.desired_name = ask(
        "What is your desired new full legal name?"
    ).strip()

    p.reason = ask(
        "What is the reason for your name change? (e.g., marriage, divorce, "
        "personal preference, gender identity, other)"
    ).strip()

    # -- DOB & SSN ----------------------------------------------------------
    p.dob = _ask_validated(
        ask,
        "What is your date of birth? (MM/DD/YYYY)",
        _validate_date,
    )

    raw_ssn = _ask_validated(
        ask,
        "What is your Social Security Number? (This will be encrypted at rest.)",
        _validate_ssn,
    )
    p.ssn_encrypted = encrypt(str(raw_ssn))

    # -- address ------------------------------------------------------------
    street = ask("Street address:").strip()
    city = ask("City:").strip()
    county = ask(
        "County or independent city (e.g., 'Fairfax', 'Richmond City'):"
    ).strip()
    zip_code = _ask_validated(ask, "ZIP code:", _validate_zip)

    p.address = Address(
        street=street,
        city=city,
        county=county,
        zip_code=str(zip_code),
    )

    # -- jurisdiction -------------------------------------------------------
    p.jurisdiction = resolve_jurisdiction(p.address)
    ask(
        f"Based on your address your petition will be filed with the "
        f"{p.jurisdiction.name}.  Filing fee is "
        f"${p.jurisdiction.filing_fee_usd:.2f}."
    )

    # -- downstream scaffolding ---------------------------------------------
    p.downstream_updates = [
        DownstreamUpdate(
            agency=d.agency,
            depends_on=list(d.depends_on),
            notes=d.notes,
        )
        for d in _DEFAULT_DOWNSTREAM
    ]

    p.advance(PetitionStatus.INTAKE)
    return p
