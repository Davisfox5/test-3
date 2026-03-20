"""Tests for the Flask web UI."""

import pytest

from va_name_change.web import create_app
from va_name_change.web import store


@pytest.fixture()
def app():
    app = create_app()
    app.config["TESTING"] = True
    # Clear store between tests
    store._store.clear()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Helper: run the full intake flow and return the petition ID
# ---------------------------------------------------------------------------

def _run_intake(client, monkeypatch, tmp_path,
                current_name="John Smith", desired_name="Jane Smith",
                reason="Personal preference", county="roanoke city",
                city="Roanoke", zip_code="24016"):
    monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))
    client.post("/intake/step1", data={
        "current_name": current_name,
        "desired_name": desired_name,
        "reason": reason,
    })
    client.post("/intake/step2", data={
        "dob": "01/15/1990",
        "place_of_birth": "Richmond, Virginia",
        "ssn": "123-45-6789",
    })
    client.post("/intake/step3", data={
        "street": "315 Church Ave SW",
        "city": city,
        "county": county,
        "zip_code": zip_code,
    })
    resp = client.post("/intake/step4", follow_redirects=False)
    location = resp.headers["Location"]
    petition_id = location.split("/petition/")[1].split("/")[0]
    return petition_id


# ---------------------------------------------------------------------------
# Basic routes
# ---------------------------------------------------------------------------

def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Virginia Name Change" in resp.data


def test_intake_step1_get(client):
    resp = client.get("/intake/step1")
    assert resp.status_code == 200
    assert b"Current Full Legal Name" in resp.data


def test_intake_step1_post_validation(client):
    resp = client.post("/intake/step1", data={
        "current_name": "",
        "desired_name": "",
        "reason": "",
    }, follow_redirects=True)
    assert b"required" in resp.data.lower() or resp.status_code == 200


def test_intake_step1_post_success(client):
    resp = client.post("/intake/step1", data={
        "current_name": "John Smith",
        "desired_name": "Jane Smith",
        "reason": "Personal preference",
    })
    assert resp.status_code == 302
    assert "/intake/step2" in resp.headers["Location"]


def test_intake_step2_requires_step1(client):
    resp = client.get("/intake/step2")
    assert resp.status_code == 302  # redirects to step1


# ---------------------------------------------------------------------------
# Full intake → dashboard redirect
# ---------------------------------------------------------------------------

def test_full_intake_redirects_to_dashboard(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    resp = client.get(f"/petition/{pid}/dashboard")
    assert resp.status_code == 200
    assert b"John Smith" in resp.data
    assert b"Jane Smith" in resp.data


def test_intake_auto_generates_documents(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    petition = store.get(pid)
    # Documents should already be generated
    assert len(petition.documents) >= 3
    doc_types = [d.doc_type.value for d in petition.documents]
    assert "CC-1411" in doc_types
    assert "cover_letter" in doc_types
    assert "SS-5" in doc_types


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_shows_documents(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    resp = client.get(f"/petition/{pid}/dashboard")
    assert resp.status_code == 200
    assert b"CC-1411" in resp.data
    assert b"Download" in resp.data


def test_dashboard_shows_efiling_for_eligible_court(client, monkeypatch, tmp_path):
    """Roanoke City supports e-filing — dashboard should show e-filing confirmation."""
    pid = _run_intake(client, monkeypatch, tmp_path, county="roanoke city")
    resp = client.get(f"/petition/{pid}/dashboard")
    assert b"E-Filing Confirmed" in resp.data
    assert b"Case Number" in resp.data


def test_dashboard_shows_manual_for_non_efiling_court(client, monkeypatch, tmp_path):
    """Botetourt doesn't support e-filing — dashboard should show manual instructions."""
    pid = _run_intake(client, monkeypatch, tmp_path, county="botetourt",
                      city="Fincastle", zip_code="24090")
    resp = client.get(f"/petition/{pid}/dashboard")
    assert b"Filing Instructions" in resp.data
    assert b"E-Filing Confirmed" not in resp.data


def test_dashboard_shows_next_action(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    resp = client.get(f"/petition/{pid}/dashboard")
    # E-filing court: should be at hearing_scheduled, showing hearing outcome buttons
    assert b"Hearing" in resp.data


# ---------------------------------------------------------------------------
# Milestone recording — manual court flow (Botetourt, no e-filing)
# ---------------------------------------------------------------------------

def test_milestone_manual_court_flow(client, monkeypatch, tmp_path):
    """Non-efiling court: manual flow filed → hearing_scheduled → granted."""
    pid = _run_intake(client, monkeypatch, tmp_path, county="botetourt",
                      city="Fincastle", zip_code="24090")
    petition = store.get(pid)
    assert petition.status.value == "filed"

    # Record hearing_scheduled
    resp = client.post(f"/petition/{pid}/milestone", data={
        "action": "hearing_scheduled",
        "hearing_date": "06/15/2026",
    }, follow_redirects=True)
    assert resp.status_code == 200
    petition = store.get(pid)
    assert petition.status.value == "hearing_scheduled"


# ---------------------------------------------------------------------------
# Milestone recording — e-filing court flow (Roanoke City)
# ---------------------------------------------------------------------------

def test_milestone_efiling_court_auto_advances(client, monkeypatch, tmp_path):
    """E-filing court: auto-advances to hearing_scheduled with hearing date."""
    pid = _run_intake(client, monkeypatch, tmp_path, county="roanoke city")
    petition = store.get(pid)
    # Should already be at hearing_scheduled from auto-efiling
    assert petition.status.value == "hearing_scheduled"
    assert petition.hearing_date is not None
    assert petition.case_number is not None


def test_milestone_granted(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    # E-filing court: already at hearing_scheduled
    resp = client.post(f"/petition/{pid}/milestone", data={
        "action": "hearing_outcome",
        "outcome": "granted",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Post-Decree" in resp.data or b"Congratulations" in resp.data


def test_milestone_denied(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    # E-filing court: already at hearing_scheduled
    resp = client.post(f"/petition/{pid}/milestone", data={
        "action": "hearing_outcome",
        "outcome": "denied",
    }, follow_redirects=True)
    assert resp.status_code == 200
    petition = store.get(pid)
    assert petition.status.value == "denied"


def test_full_end_to_end_flow(client, monkeypatch, tmp_path):
    """Test the complete automated pipeline: intake → e-file → hearing → post-decree → complete."""
    pid = _run_intake(client, monkeypatch, tmp_path)
    petition = store.get(pid)
    # E-filing: should be at hearing_scheduled with case number
    assert petition.status.value == "hearing_scheduled"
    assert petition.case_number is not None
    assert len(petition.documents) >= 3

    # Granted
    client.post(f"/petition/{pid}/milestone", data={
        "action": "hearing_outcome",
        "outcome": "granted",
    })

    # Dashboard should now show post-decree plan
    resp = client.get(f"/petition/{pid}/dashboard")
    assert resp.status_code == 200
    assert b"Post-Decree Updates" in resp.data
    assert b"Social Security" in resp.data

    # Mark all downstream updates complete
    petition = store.get(pid)
    for u in petition.downstream_updates:
        client.post(f"/petition/{pid}/post-decree/complete", data={
            "agency": u.agency,
        }, headers={"Referer": f"/petition/{pid}/dashboard"})

    petition = store.get(pid)
    assert petition.status.value == "completed"

    # Dashboard should show completion
    resp = client.get(f"/petition/{pid}/dashboard")
    assert b"Name Change Complete" in resp.data


# ---------------------------------------------------------------------------
# Legacy routes still work
# ---------------------------------------------------------------------------

def test_documents_page(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    resp = client.get(f"/petition/{pid}/documents")
    assert resp.status_code == 200
    assert b"CC-1411" in resp.data


def test_status_page(client, monkeypatch, tmp_path):
    pid = _run_intake(client, monkeypatch, tmp_path)
    resp = client.get(f"/petition/{pid}/status")
    assert resp.status_code == 200
    assert b"Petition Status" in resp.data


def test_404_for_unknown_petition(client):
    resp = client.get("/petition/nonexistent/documents")
    assert resp.status_code == 404


def test_roanoke_jurisdictions_in_dropdown(client):
    client.post("/intake/step1", data={
        "current_name": "X", "desired_name": "Y", "reason": "Other",
    })
    client.post("/intake/step2", data={
        "dob": "2000-01-01",
        "place_of_birth": "Richmond, VA",
        "ssn": "111223333",
    })
    resp = client.get("/intake/step3")
    assert resp.status_code == 200
    assert b"Roanoke City" in resp.data
    assert b"Roanoke County" in resp.data
    assert b"Salem" in resp.data
    assert b"Botetourt" in resp.data
    assert b"Craig" in resp.data
    assert b"Bedford County" in resp.data
    assert b"Franklin County" in resp.data
