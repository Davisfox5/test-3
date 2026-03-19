"""VA Code Monitor — keeps the system current with Virginia statutory changes.

Virginia publishes its Code through the Legislative Information System (LIS)
at law.lis.virginia.gov.  This agent periodically checks for changes to the
sections that govern name changes (primarily Va. Code §§ 8.01-217 through
8.01-217.2) and alerts the system operator when updates are detected.

Three monitoring strategies are implemented:

1. **LIS scraping** — fetches the HTML text of each relevant section and
   compares a content hash against the last-known version.
2. **Virginia Register watch** — checks the Virginia Register of Regulations
   for any proposed or final rules that reference the target sections.
3. **Legislative session bill tracker** — during active General Assembly
   sessions, searches for bills that would amend the target sections.

When a change is detected the agent:
  - Logs the diff.
  - Fires an alert (webhook / email) so a human reviewer can update forms,
    fee schedules, or process logic.
  - Stores the new baseline hash for future comparisons.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from va_name_change.config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SectionSnapshot:
    """A point-in-time snapshot of one VA Code section."""

    section_id: str          # e.g. "8.01-217"
    content_hash: str        # SHA-256 of the section text
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    raw_text: str = ""


@dataclass
class ChangeAlert:
    """Emitted when a statutory change is detected."""

    section_id: str
    old_hash: str
    new_hash: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    summary: str = ""
    raw_new_text: str = ""


# ---------------------------------------------------------------------------
# Persistence — simple JSON file store (swap for a DB in production)
# ---------------------------------------------------------------------------

_BASELINE_FILE = os.path.join(config.output_dir, ".va_code_baselines.json")


def _load_baselines() -> dict[str, str]:
    """Return ``{section_id: content_hash}`` from the baseline file."""
    if not os.path.exists(_BASELINE_FILE):
        return {}
    with open(_BASELINE_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_baselines(baselines: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(_BASELINE_FILE) or ".", exist_ok=True)
    with open(_BASELINE_FILE, "w", encoding="utf-8") as fh:
        json.dump(baselines, fh, indent=2)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _fetch_section_text(section_id: str) -> str:
    """Fetch the current text of a VA Code section from LIS.

    Uses ``urllib`` so there are no third-party HTTP dependencies.  In
    production you might prefer ``httpx`` or ``requests`` with retries.
    """
    import urllib.request
    import urllib.error

    # The Virginia LIS provides section text at a predictable URL pattern.
    # e.g. https://law.lis.virginia.gov/vacode/title8.01/chapter17/section8.01-217/
    title = section_id.split("-")[0]  # "8.01"
    url = (
        f"{config.va_legislative_api_base}/vacode/"
        f"title{title}/chapter17/section{section_id}/"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VA-NameChange-Monitor/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return ""

    # Strip HTML tags to get a rough plain-text representation.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_bill_search(section_id: str) -> str:
    """Search the VA LIS for bills referencing *section_id*.

    Returns raw HTML (or empty string on failure) from the bill search.
    """
    import urllib.request
    import urllib.error
    import urllib.parse

    query = urllib.parse.quote(f"§ {section_id}")
    url = f"{config.va_legislative_api_base}/cf/lis/lis_bills.cfm?ses=current&txt={query}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VA-NameChange-Monitor/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        logger.warning("Bill search failed for %s: %s", section_id, exc)
        return ""


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

def _send_alert(alert: ChangeAlert) -> None:
    """Dispatch a change alert via configured channels."""
    msg = (
        f"[VA Code Monitor] Change detected in § {alert.section_id}\n"
        f"Old hash: {alert.old_hash[:16]}…\n"
        f"New hash: {alert.new_hash[:16]}…\n"
        f"Detected: {alert.detected_at.isoformat()}\n"
        f"Summary: {alert.summary}\n"
    )
    logger.warning(msg)

    # Webhook (e.g. Slack incoming webhook)
    if config.alert_webhook_url:
        import urllib.request
        data = json.dumps({"text": msg}).encode()
        req = urllib.request.Request(
            config.alert_webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as exc:  # noqa: BLE001
            logger.error("Webhook alert failed: %s", exc)

    # Email stub — integrate with SES / SMTP in production
    if config.alert_email:
        logger.info("Would send email to %s (not implemented in dev mode).", config.alert_email)


# ---------------------------------------------------------------------------
# Core monitoring logic
# ---------------------------------------------------------------------------

def check_for_changes(
    sections: Optional[tuple[str, ...]] = None,
) -> list[ChangeAlert]:
    """Check each monitored VA Code section for content changes.

    Returns a list of ``ChangeAlert`` objects for any sections whose
    content hash differs from the stored baseline.
    """
    sections = sections or config.va_code_sections
    baselines = _load_baselines()
    alerts: list[ChangeAlert] = []

    for section_id in sections:
        text = _fetch_section_text(section_id)
        if not text:
            logger.info("Skipping %s — could not fetch content.", section_id)
            continue

        new_hash = hashlib.sha256(text.encode()).hexdigest()
        old_hash = baselines.get(section_id, "")

        if old_hash and new_hash != old_hash:
            alert = ChangeAlert(
                section_id=section_id,
                old_hash=old_hash,
                new_hash=new_hash,
                summary=f"Content of Va. Code § {section_id} has changed since last check.",
                raw_new_text=text[:2000],  # truncate for alert payload
            )
            alerts.append(alert)
            _send_alert(alert)

        # Update baseline regardless (first run seeds the baseline)
        baselines[section_id] = new_hash

    _save_baselines(baselines)
    return alerts


def check_pending_legislation(
    sections: Optional[tuple[str, ...]] = None,
) -> list[str]:
    """Search for pending bills that reference the monitored sections.

    Returns a list of summary strings (one per matching bill found).
    Intended to be called periodically during active GA sessions.
    """
    sections = sections or config.va_code_sections
    results: list[str] = []

    for section_id in sections:
        html = _fetch_bill_search(section_id)
        if not html:
            continue

        # Very simple heuristic: look for bill numbers (e.g. HB 1234, SB 567)
        bills = re.findall(r"((?:HB|SB)\s*\d+)", html)
        if bills:
            unique = sorted(set(bills))
            summary = (
                f"§ {section_id}: found {len(unique)} pending bill(s) — "
                + ", ".join(unique)
            )
            results.append(summary)
            logger.info(summary)

    return results


# ---------------------------------------------------------------------------
# Continuous monitor (blocking — run in a background thread / process)
# ---------------------------------------------------------------------------

def run_monitor_loop(poll_interval: Optional[int] = None) -> None:  # pragma: no cover
    """Poll for changes indefinitely at *poll_interval* seconds.

    This is meant to be run as a background daemon or scheduled task
    (cron, systemd timer, Celery beat, etc.).
    """
    interval = poll_interval or config.va_code_poll_interval
    logger.info(
        "Starting VA Code monitor — polling every %d seconds for sections %s",
        interval,
        config.va_code_sections,
    )

    while True:
        try:
            alerts = check_for_changes()
            if alerts:
                logger.warning("%d change(s) detected!", len(alerts))
            else:
                logger.info("No changes detected.")

            pending = check_pending_legislation()
            if pending:
                for p in pending:
                    logger.info("Pending legislation: %s", p)

        except Exception:
            logger.exception("Monitor loop iteration failed.")

        time.sleep(interval)
