"""Tests for the post-decree agent."""

from va_name_change.agents.post_decree import (
    build_update_plan,
    format_plan,
    mark_update_complete,
)
from va_name_change.models import (
    DownstreamStatus,
    DownstreamUpdate,
    NameChangePetition,
)


def _petition_with_updates() -> NameChangePetition:
    p = NameChangePetition()
    p.downstream_updates = [
        DownstreamUpdate(agency="SSA"),
        DownstreamUpdate(agency="VA DMV", depends_on=["SSA"]),
        DownstreamUpdate(agency="US Passport", depends_on=["SSA"]),
        DownstreamUpdate(agency="Utilities"),
    ]
    return p


def test_build_update_plan_tiers():
    p = _petition_with_updates()
    plan = build_update_plan(p)

    # Tier 1 should contain SSA and Utilities (no dependencies)
    tier1_agencies = {a.agency for a in plan[0]}
    assert "Social Security Administration" in tier1_agencies or "SSA" in tier1_agencies
    assert len(plan) >= 2


def test_mark_update_complete():
    p = _petition_with_updates()
    result = mark_update_complete(p, "SSA")
    assert result is not None
    assert result.status == DownstreamStatus.COMPLETED


def test_format_plan():
    p = _petition_with_updates()
    plan = build_update_plan(p)
    text = format_plan(plan)
    assert "TIER 1" in text
    assert "TIER 2" in text
