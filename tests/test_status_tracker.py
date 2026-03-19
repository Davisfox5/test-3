"""Tests for the status tracker / state machine."""

from datetime import date, timedelta

import pytest

from va_name_change.agents.status_tracker import (
    InvalidTransitionError,
    PetitionTimeline,
    build_default_timeline,
    format_timeline,
    safe_advance,
    validate_transition,
)
from va_name_change.models import NameChangePetition, PetitionStatus


def test_valid_transitions():
    validate_transition(PetitionStatus.INTAKE, PetitionStatus.FORMS_READY)
    validate_transition(PetitionStatus.FILED, PetitionStatus.HEARING_SCHEDULED)
    validate_transition(PetitionStatus.HEARING_SCHEDULED, PetitionStatus.GRANTED)


def test_invalid_transition():
    with pytest.raises(InvalidTransitionError):
        validate_transition(PetitionStatus.INTAKE, PetitionStatus.GRANTED)


def test_safe_advance():
    p = NameChangePetition()
    p.status = PetitionStatus.INTAKE
    safe_advance(p, PetitionStatus.FORMS_READY)
    assert p.status == PetitionStatus.FORMS_READY


def test_safe_advance_invalid():
    p = NameChangePetition()
    p.status = PetitionStatus.INTAKE
    with pytest.raises(InvalidTransitionError):
        safe_advance(p, PetitionStatus.COMPLETED)


def test_timeline_overdue():
    tl = PetitionTimeline(petition_id="test")
    tl.add("Past deadline", date.today() - timedelta(days=5))
    tl.add("Future deadline", date.today() + timedelta(days=5))
    assert len(tl.overdue()) == 1


def test_timeline_upcoming():
    tl = PetitionTimeline(petition_id="test")
    tl.add("Soon", date.today() + timedelta(days=3))
    tl.add("Far out", date.today() + timedelta(days=30))
    upcoming = tl.upcoming(days=7)
    assert len(upcoming) == 1


def test_build_default_timeline():
    p = NameChangePetition()
    tl = build_default_timeline(p)
    assert len(tl.deadlines) >= 5


def test_format_timeline():
    p = NameChangePetition()
    tl = build_default_timeline(p)
    text = format_timeline(tl)
    assert "[ ]" in text
    assert p.petition_id in text
