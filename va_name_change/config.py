"""Configuration and constants for the VA name-change system."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class AppConfig:
    """Runtime configuration — populated from env vars / dotenv."""

    # Directory where generated PDFs are stored
    output_dir: str = os.getenv("VNC_OUTPUT_DIR", "./output")

    # VA Code monitoring
    va_legislative_api_base: str = "https://law.lis.virginia.gov"
    va_code_title: str = "8.01"       # Title 8.01 — Civil Remedies and Procedure
    va_code_sections: tuple[str, ...] = ("8.01-217", "8.01-217.1", "8.01-217.2")

    # Notification channel (e.g. email, Slack webhook, etc.)
    alert_webhook_url: str = os.getenv("VNC_ALERT_WEBHOOK", "")
    alert_email: str = os.getenv("VNC_ALERT_EMAIL", "")

    # Polling interval for VA Code changes (seconds)
    va_code_poll_interval: int = int(os.getenv("VNC_POLL_INTERVAL", "86400"))  # 1 day

    # PDF form templates directory
    templates_dir: str = os.getenv("VNC_TEMPLATES_DIR", "./templates")


config = AppConfig()
