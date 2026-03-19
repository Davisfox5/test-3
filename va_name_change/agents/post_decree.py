"""Post-Decree Agent — orchestrates downstream identity updates.

After the court grants the name-change order, dozens of agencies and
institutions need to be notified.  This agent manages the dependency
graph (e.g. SSA must be updated before DMV) and produces actionable
checklists for each update.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from va_name_change.models import (
    DownstreamStatus,
    DownstreamUpdate,
    NameChangePetition,
    PetitionStatus,
)


@dataclass
class UpdateAction:
    """A concrete step the petitioner should take for one downstream update."""

    agency: str
    instructions: list[str]
    required_documents: list[str]
    website: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Agency-specific playbooks
# ---------------------------------------------------------------------------

_PLAYBOOKS: dict[str, UpdateAction] = {
    "SSA": UpdateAction(
        agency="Social Security Administration",
        instructions=[
            "Complete Form SS-5 (already generated in your output folder).",
            "Bring the certified court order and a valid photo ID to your local SSA office.",
            "You may also mail the application — see ssa.gov for your local office address.",
            "Allow 2-4 weeks to receive your new Social Security card.",
        ],
        required_documents=["Certified court order", "Valid photo ID", "Form SS-5"],
        website="https://www.ssa.gov/myaccount/",
    ),
    "VA DMV": UpdateAction(
        agency="Virginia Department of Motor Vehicles",
        instructions=[
            "Visit any Virginia DMV location or use DMV Connect.",
            "Bring your certified court order AND your new Social Security card.",
            "Complete the Virginia DL/ID application.",
            "Pay the applicable fee for a replacement license/ID.",
        ],
        required_documents=[
            "Certified court order",
            "New Social Security card",
            "Current Virginia DL/ID",
            "Proof of residency (two documents)",
        ],
        website="https://www.dmv.virginia.gov/",
    ),
    "US Passport": UpdateAction(
        agency="U.S. Department of State — Passport Services",
        instructions=[
            "If your current passport was issued less than one year ago, submit Form DS-5504 (correction).",
            "Otherwise, submit Form DS-11 (new passport application).",
            "Include a certified court order with your application.",
            "Submit by mail or at an acceptance facility.",
        ],
        required_documents=[
            "Certified court order",
            "Current passport (if applicable)",
            "Passport photo",
            "Form DS-11 or DS-5504",
        ],
        website="https://travel.state.gov/",
    ),
    "Birth Certificate": UpdateAction(
        agency="Vital Records — State of Birth",
        instructions=[
            "Contact the vital records office in your state of birth.",
            "If born in Virginia, contact the Virginia Department of Health, Division of Vital Records.",
            "Submit a certified court order and a completed amendment request.",
            "Fees and processing times vary by state.",
        ],
        required_documents=["Certified court order", "Amendment request form", "Payment"],
        website="https://www.vdh.virginia.gov/vital-records/",
    ),
    "Voter Registration": UpdateAction(
        agency="Virginia Department of Elections",
        instructions=[
            "Update your voter registration online at vote.virginia.gov.",
            "You will need your new Virginia DL/ID number.",
        ],
        required_documents=["New Virginia DL/ID"],
        website="https://vote.virginia.gov/",
    ),
    "Banks / Financial": UpdateAction(
        agency="Banks and Financial Institutions",
        instructions=[
            "Visit each bank/credit union in person with your certified court order and new ID.",
            "Update checking, savings, credit cards, loans, and investment accounts.",
            "Don't forget retirement accounts (401k, IRA).",
        ],
        required_documents=["Certified court order", "New government-issued ID"],
    ),
    "Employer / HR": UpdateAction(
        agency="Employer / Human Resources",
        instructions=[
            "Notify your HR department and provide a copy of the court order.",
            "Update your W-4, direct deposit, benefits, and email/directory listings.",
        ],
        required_documents=["Certified court order or new Social Security card"],
    ),
    "Utilities": UpdateAction(
        agency="Utility Companies",
        instructions=[
            "Contact each utility provider (electric, gas, water, internet, phone).",
            "Most can be updated over the phone or online with your new name.",
        ],
        required_documents=["New government-issued ID (may be requested)"],
    ),
    "Professional Licenses": UpdateAction(
        agency="Professional Licensing Boards",
        instructions=[
            "Contact each licensing board (medical, legal, real estate, etc.).",
            "Submit a certified court order and any required amendment forms.",
            "Fees and processing times vary by board.",
        ],
        required_documents=["Certified court order", "Board-specific amendment form"],
    ),
}


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------

def _topological_order(updates: list[DownstreamUpdate]) -> list[list[str]]:
    """Return a list of *tiers* — groups that can be processed in parallel.

    Within each tier, all items are independent of one another.  Later tiers
    depend on earlier ones.
    """
    # Build adjacency
    in_degree: dict[str, int] = defaultdict(int)
    dependents: dict[str, list[str]] = defaultdict(list)
    all_agencies = {u.agency for u in updates}

    for u in updates:
        in_degree.setdefault(u.agency, 0)
        for dep in u.depends_on:
            if dep in all_agencies:
                dependents[dep].append(u.agency)
                in_degree[u.agency] += 1

    queue: deque[str] = deque(a for a in all_agencies if in_degree[a] == 0)
    tiers: list[list[str]] = []

    while queue:
        tier = list(queue)
        tiers.append(tier)
        next_queue: deque[str] = deque()
        for node in tier:
            for dep in dependents[node]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    next_queue.append(dep)
        queue = next_queue

    return tiers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_update_plan(petition: NameChangePetition) -> list[list[UpdateAction]]:
    """Return a tiered execution plan for all downstream updates.

    Each inner list is a *tier* of updates that can be done in parallel.
    """
    tiers = _topological_order(petition.downstream_updates)
    plan: list[list[UpdateAction]] = []
    for tier_agencies in tiers:
        tier_actions = []
        for agency in tier_agencies:
            action = _PLAYBOOKS.get(agency)
            if action:
                tier_actions.append(action)
            else:
                tier_actions.append(UpdateAction(
                    agency=agency,
                    instructions=[f"Contact {agency} and provide your certified court order."],
                    required_documents=["Certified court order"],
                ))
        plan.append(tier_actions)
    return plan


def mark_update_complete(
    petition: NameChangePetition, agency: str
) -> Optional[DownstreamUpdate]:
    """Mark a downstream update as completed and return it."""
    for u in petition.downstream_updates:
        if u.agency == agency:
            u.status = DownstreamStatus.COMPLETED
            if petition.all_downstream_complete():
                petition.advance(PetitionStatus.COMPLETED)
            return u
    return None


def format_plan(plan: list[list[UpdateAction]]) -> str:
    """Render the tiered plan as human-readable text."""
    lines: list[str] = []
    for tier_idx, tier in enumerate(plan, 1):
        lines.append(f"\n{'='*60}")
        lines.append(f"  TIER {tier_idx} (these can be done in parallel)")
        lines.append(f"{'='*60}")
        for action in tier:
            lines.append(f"\n  --- {action.agency} ---")
            for i, step in enumerate(action.instructions, 1):
                lines.append(f"    {i}. {step}")
            lines.append(f"    Documents needed: {', '.join(action.required_documents)}")
            if action.website:
                lines.append(f"    Website: {action.website}")
    return "\n".join(lines)
