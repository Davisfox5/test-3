"""Tests for the intake agent."""

from collections import deque

from va_name_change.agents.intake import run_intake
from va_name_change.models import PetitionStatus


def _make_ask(answers: list[str]):
    """Return an ask function that pops answers from a list."""
    q = deque(answers)

    def ask(prompt: str) -> str:
        return q.popleft()

    return ask


def test_full_intake():
    answers = [
        "John Smith",            # current legal name
        "Jane Smith",            # desired name
        "personal preference",   # reason
        "01/15/1990",            # DOB
        "123-45-6789",           # SSN
        "123 Main St",           # street
        "Fairfax",               # city
        "Fairfax",               # county
        "22030",                 # zip
        "ok",                    # jurisdiction confirmation
    ]
    ask = _make_ask(answers)
    petition = run_intake(ask)

    assert petition.current_legal_name == "John Smith"
    assert petition.desired_name == "Jane Smith"
    assert petition.dob is not None
    assert petition.address is not None
    assert petition.jurisdiction is not None
    assert "Fairfax" in petition.jurisdiction.name
    assert petition.status == PetitionStatus.INTAKE
    assert len(petition.downstream_updates) > 0
