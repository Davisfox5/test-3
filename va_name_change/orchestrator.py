"""Main Orchestrator — ties every agent together into a single pipeline.

Usage (CLI demo)::

    python -m va_name_change.orchestrator

The orchestrator drives the petition through every lifecycle phase:

    INTAKE → FORMS_READY → FILED → HEARING_SCHEDULED → GRANTED
           → POST_DECREE_IN_PROGRESS → COMPLETED

At each human-in-the-loop checkpoint it pauses for confirmation.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable

from va_name_change.agents.intake import run_intake
from va_name_change.agents.forms import generate_all_forms
from va_name_change.agents.filing import prepare_filing, format_instructions
from va_name_change.agents.post_decree import (
    build_update_plan,
    format_plan,
    mark_update_complete,
)
from va_name_change.agents.status_tracker import (
    build_default_timeline,
    format_timeline,
    safe_advance,
)
from va_name_change.agents.va_code_monitor import check_for_changes, check_pending_legislation
from va_name_change.models import NameChangePetition, PetitionStatus

logger = logging.getLogger(__name__)

AskFn = Callable[[str], str]


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _cli_ask(prompt: str) -> str:
    """Simple stdin/stdout interaction for the CLI demo."""
    print(f"\n>> {prompt}")
    return input("   → ").strip()


def _cli_confirm(prompt: str) -> bool:
    answer = _cli_ask(f"{prompt} (yes/no)")
    return answer.lower() in ("yes", "y")


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def stage_intake(ask: AskFn) -> NameChangePetition:
    """Phase 1: collect petitioner info."""
    print("\n" + "=" * 60)
    print("  PHASE 1 — INTAKE")
    print("=" * 60)
    return run_intake(ask)


def stage_forms(petition: NameChangePetition, ask: AskFn) -> None:
    """Phase 2: generate all required documents."""
    print("\n" + "=" * 60)
    print("  PHASE 2 — DOCUMENT GENERATION")
    print("=" * 60)

    docs = generate_all_forms(petition)
    print(f"\nGenerated {len(docs)} document(s):")
    for doc in docs:
        print(f"  • {doc.doc_type.value:30s}  →  {doc.file_path}")

    ask("Please review the generated documents in your output folder before proceeding.")


def stage_filing(petition: NameChangePetition, ask: AskFn) -> None:
    """Phase 3: produce filing instructions and await confirmation."""
    print("\n" + "=" * 60)
    print("  PHASE 3 — FILING")
    print("=" * 60)

    instructions = prepare_filing(petition)
    print(format_instructions(instructions))

    timeline = build_default_timeline(petition)
    print("\n" + format_timeline(timeline))

    ask("Have you filed the petition with the court? (Confirm when done.)")
    safe_advance(petition, PetitionStatus.HEARING_SCHEDULED)


def stage_hearing(petition: NameChangePetition, ask: AskFn) -> None:
    """Phase 4: wait for hearing outcome."""
    print("\n" + "=" * 60)
    print("  PHASE 4 — HEARING")
    print("=" * 60)

    result = ask(
        "What was the outcome of your hearing? (granted / denied)"
    ).lower()

    if result in ("granted", "g", "yes"):
        safe_advance(petition, PetitionStatus.GRANTED)
        print("Congratulations! Your name change has been granted.")
    else:
        safe_advance(petition, PetitionStatus.DENIED)
        print("The petition was denied. Please consult an attorney for next steps.")


def stage_post_decree(petition: NameChangePetition, ask: AskFn) -> None:
    """Phase 5: guide through downstream identity updates."""
    print("\n" + "=" * 60)
    print("  PHASE 5 — POST-DECREE UPDATES")
    print("=" * 60)

    safe_advance(petition, PetitionStatus.POST_DECREE_IN_PROGRESS)
    plan = build_update_plan(petition)
    print(format_plan(plan))

    # Walk through each tier interactively
    for tier_idx, tier in enumerate(plan, 1):
        print(f"\n--- Tier {tier_idx} ---")
        for action in tier:
            ask(f"Have you completed the update for {action.agency}? (Confirm when done.)")
            mark_update_complete(petition, action.agency)
            print(f"  ✓ {action.agency} marked complete.")

    if petition.all_downstream_complete():
        petition.advance(PetitionStatus.COMPLETED)
        print("\nAll downstream updates are complete. Your name change process is finished!")


# ---------------------------------------------------------------------------
# VA Code currency check
# ---------------------------------------------------------------------------

def stage_va_code_check() -> None:
    """Optional pre-flight: verify the system is current with VA Code."""
    print("\n" + "=" * 60)
    print("  PRE-FLIGHT — VA CODE CURRENCY CHECK")
    print("=" * 60)

    alerts = check_for_changes()
    if alerts:
        print(f"\n⚠  {len(alerts)} statutory change(s) detected:")
        for a in alerts:
            print(f"   § {a.section_id}: {a.summary}")
        print("   Please review before proceeding.\n")
    else:
        print("  VA Code sections are up to date.\n")

    pending = check_pending_legislation()
    if pending:
        print("  Pending legislation that may affect name changes:")
        for p in pending:
            print(f"    • {p}")
    else:
        print("  No pending legislation found.\n")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pipeline(ask: AskFn | None = None, skip_va_check: bool = False) -> NameChangePetition:
    """Execute the full name-change pipeline end to end.

    Parameters
    ----------
    ask:
        A callable ``(prompt) -> str`` for user interaction.  Defaults to
        stdin/stdout for CLI usage.
    skip_va_check:
        If *True*, skip the VA Code currency pre-flight check (useful for
        offline / test environments).
    """
    ask = ask or _cli_ask

    print("=" * 60)
    print("  VIRGINIA NAME CHANGE — AGENTIC PIPELINE")
    print("=" * 60)

    if not skip_va_check:
        try:
            stage_va_code_check()
        except Exception:
            logger.warning("VA Code check failed — proceeding anyway.", exc_info=True)

    petition = stage_intake(ask)
    stage_forms(petition, ask)
    stage_filing(petition, ask)
    stage_hearing(petition, ask)

    if petition.status == PetitionStatus.GRANTED:
        stage_post_decree(petition, ask)

    print("\n" + "=" * 60)
    print(f"  PIPELINE COMPLETE — Status: {petition.status.value}")
    print("=" * 60)
    return petition


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_pipeline()
    except (KeyboardInterrupt, EOFError):
        print("\nPipeline interrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
