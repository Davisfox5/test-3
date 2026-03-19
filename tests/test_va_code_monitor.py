"""Tests for the VA Code monitor."""

import json
import os
from unittest.mock import patch

from va_name_change.agents.va_code_monitor import (
    SectionSnapshot,
    _load_baselines,
    _save_baselines,
    check_for_changes,
)


def test_save_and_load_baselines(tmp_path, monkeypatch):
    baseline_file = str(tmp_path / ".va_code_baselines.json")
    monkeypatch.setattr(
        "va_name_change.agents.va_code_monitor._BASELINE_FILE", baseline_file
    )

    _save_baselines({"8.01-217": "abc123"})
    loaded = _load_baselines()
    assert loaded == {"8.01-217": "abc123"}


def test_check_for_changes_detects_diff(tmp_path, monkeypatch):
    """Simulate a content change by seeding a baseline then returning different text."""
    baseline_file = str(tmp_path / ".va_code_baselines.json")
    monkeypatch.setattr(
        "va_name_change.agents.va_code_monitor._BASELINE_FILE", baseline_file
    )

    # Seed a baseline with a known hash
    import hashlib
    old_text = "old version of the statute"
    old_hash = hashlib.sha256(old_text.encode()).hexdigest()
    _save_baselines({"8.01-217": old_hash})

    # Mock the fetch to return new text
    new_text = "new amended version of the statute"
    with patch(
        "va_name_change.agents.va_code_monitor._fetch_section_text",
        return_value=new_text,
    ):
        alerts = check_for_changes(sections=("8.01-217",))

    assert len(alerts) == 1
    assert alerts[0].section_id == "8.01-217"
    assert alerts[0].old_hash == old_hash
    assert alerts[0].new_hash != old_hash


def test_check_for_changes_no_diff(tmp_path, monkeypatch):
    """When content hasn't changed, no alerts should be emitted."""
    baseline_file = str(tmp_path / ".va_code_baselines.json")
    monkeypatch.setattr(
        "va_name_change.agents.va_code_monitor._BASELINE_FILE", baseline_file
    )

    import hashlib
    text = "unchanged statute text"
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    _save_baselines({"8.01-217": text_hash})

    with patch(
        "va_name_change.agents.va_code_monitor._fetch_section_text",
        return_value=text,
    ):
        alerts = check_for_changes(sections=("8.01-217",))

    assert len(alerts) == 0
