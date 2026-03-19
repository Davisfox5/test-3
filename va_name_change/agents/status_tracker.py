"""Status Tracker — state machine and deadline management.

Maintains the lifecycle of a petition through well-defined transitions
and tracks key dates (filing date, hearing date, publication windows,
document expiration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from va_name_change.models import NameChangePetition, PetitionStatus

# ---------------------------------------------------------------------------
# Allowed state transitions
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[PetitionStatus, set[PetitionStatus]] = {
    PetitionStatus.INTAKE: {PetitionStatus.FORMS_READY},
    PetitionStatus.FORMS_READY: {PetitionStatus.FILED},
    PetitionStatus.FILED: {PetitionStatus.HEARING_SCHEDULED, PetitionStatus.DENIED},
    PetitionStatus.HEARING_SCHEDULED: {PetitionStatus.GRANTED, PetitionStatus.DENIED},
    PetitionStatus.GRANTED: {PetitionStatus.POST_DECREE_IN_PROGRESS},
    PetitionStatus.POST_DECREE_IN_PROGRESS: {PetitionStatus.COMPLETED},
    PetitionStatus.COMPLETED: set(),
    PetitionStatus.DENIED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed."""


def validate_transition(current: PetitionStatus, target: PetitionStatus) -> None:
    """Raise ``InvalidTransitionError`` if *current* → *target* is illegal."""
    allowed = _TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {current.value!r} to {target.value!r}. "
            f"Allowed targets: {sorted(s.value for s in allowed)}"
        )


def safe_advance(petition: NameChangePetition, target: PetitionStatus) -> None:
    """Transition *petition* to *target* with validation."""
    validate_transition(petition.status, target)
    petition.advance(target)


# ---------------------------------------------------------------------------
# Deadline / reminder tracking
# ---------------------------------------------------------------------------

@dataclass
class Deadline:
    label: str
    due_date: date
    completed: bool = False
    notes: str = ""


@dataclass
class PetitionTimeline:
    """Tracks all key deadlines for a single petition."""

    petition_id: str
    deadlines: list[Deadline] = field(default_factory=list)

    def add(self, label: str, due: date, notes: str = "") -> None:
        self.deadlines.append(Deadline(label=label, due_date=due, notes=notes))

    def overdue(self, as_of: Optional[date] = None) -> list[Deadline]:
        ref = as_of or date.today()
        return [d for d in self.deadlines if not d.completed and d.due_date < ref]

    def upcoming(self, days: int = 7, as_of: Optional[date] = None) -> list[Deadline]:
        ref = as_of or date.today()
        cutoff = ref + timedelta(days=days)
        return [
            d for d in self.deadlines
            if not d.completed and ref <= d.due_date <= cutoff
        ]

    def mark_complete(self, label: str) -> bool:
        for d in self.deadlines:
            if d.label == label:
                d.completed = True
                return True
        return False


def build_default_timeline(
    petition: NameChangePetition,
    filed_date: Optional[date] = None,
) -> PetitionTimeline:
    """Create a timeline with standard Virginia deadlines.

    Dates are approximate and should be adjusted once the court provides
    exact scheduling information.
    """
    tl = PetitionTimeline(petition_id=petition.petition_id)
    base = filed_date or date.today()

    tl.add("Submit fingerprints", base + timedelta(days=7),
           "Fingerprint card must be submitted to the clerk.")
    tl.add("Publication window opens", base + timedelta(days=7),
           "Begin newspaper publication if required by jurisdiction.")
    tl.add("Publication window closes", base + timedelta(days=28),
           "Publication must run once/week for the required period.")
    tl.add("Estimated hearing date", base + timedelta(days=56),
           "Approximate — confirm with clerk's office.")
    tl.add("SSA update (post-decree)", base + timedelta(days=70),
           "Update Social Security within ~2 weeks of court order.")
    tl.add("DMV update (post-decree)", base + timedelta(days=84),
           "Update VA DMV after receiving new SS card.")

    return tl


def format_timeline(tl: PetitionTimeline) -> str:
    """Render the timeline as a human-readable checklist."""
    lines = [f"Timeline for petition {tl.petition_id}:", ""]
    for d in sorted(tl.deadlines, key=lambda x: x.due_date):
        check = "[x]" if d.completed else "[ ]"
        lines.append(f"  {check} {d.due_date.isoformat()}  {d.label}")
        if d.notes:
            lines.append(f"      {d.notes}")
    return "\n".join(lines)
