"""Tests for the e-filing agent and VJEFS client."""

import os
from datetime import date

import pytest

from va_name_change.agents.efiling import can_efile, submit_efiling, poll_filing_status
from va_name_change.agents.forms import generate_all_forms
from va_name_change.models import (
    Address,
    NameChangePetition,
    PetitionStatus,
)
from va_name_change.services.vjefs_client import (
    EFilingStatus,
    EFilingSubmission,
    VJEFSSimulator,
)
from va_name_change.utils.jurisdiction import resolve_jurisdiction


def _make_petition(county: str = "roanoke city") -> NameChangePetition:
    addr = Address(street="315 Church Ave SW", city="Roanoke",
                   county=county, zip_code="24016")
    p = NameChangePetition(
        current_legal_name="John Smith",
        desired_name="Jane Smith",
        reason="Personal preference",
        dob=date(1990, 1, 15),
        place_of_birth="Richmond, Virginia",
        ssn_encrypted="encrypted",
        address=addr,
        jurisdiction=resolve_jurisdiction(addr),
    )
    p.advance(PetitionStatus.INTAKE)
    return p


# ---------------------------------------------------------------------------
# VJEFS Simulator
# ---------------------------------------------------------------------------

class TestVJEFSSimulator:
    def test_full_workflow(self):
        sim = VJEFSSimulator()

        # Create envelope
        env = sim.create_envelope("770")
        assert "envelope_id" in env
        eid = env["envelope_id"]

        # Upload document
        doc = sim.upload_document(eid, "/tmp/fake.pdf", "PETITION")
        assert doc["status"] == "UPLOADED"

        # Pay
        pay = sim.submit_payment(eid, 53.00)
        assert pay["status"] == "COMPLETED"
        assert "transaction_id" in pay

        # Submit
        sub = sim.submit_filing(eid)
        assert sub["status"] == "SUBMITTED"
        assert sub["case_number"].startswith("CL")
        assert sub["confirmation_code"]

        # Status
        status = sim.get_filing_status(eid)
        assert status["status"] == "ACCEPTED"
        assert status["case_number"]
        assert status["hearing_date"]

    def test_payment_required_before_submit(self):
        sim = VJEFSSimulator()
        env = sim.create_envelope("770")
        with pytest.raises(Exception, match="Payment required"):
            sim.submit_filing(env["envelope_id"])

    def test_case_details(self):
        sim = VJEFSSimulator()
        env = sim.create_envelope("770")
        eid = env["envelope_id"]
        sim.upload_document(eid, "/tmp/fake.pdf", "PETITION")
        sim.submit_payment(eid, 53.00)
        sim.submit_filing(eid)

        details = sim.get_case_details(eid)
        assert details["case_number"]
        assert details["hearing_date"]
        assert details["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# E-Filing Agent
# ---------------------------------------------------------------------------

class TestEFilingAgent:
    def test_can_efile_true(self):
        p = _make_petition("roanoke city")
        assert can_efile(p) is True

    def test_can_efile_false(self):
        p = _make_petition("botetourt")
        assert can_efile(p) is False

    def test_submit_efiling_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))
        p = _make_petition("roanoke city")
        generate_all_forms(p)

        result = submit_efiling(p)

        assert result.success is True
        assert result.method == "efiled"
        assert result.submission.case_number is not None
        assert result.submission.confirmation_code is not None
        assert result.submission.hearing_date is not None
        assert result.submission.status == EFilingStatus.ACCEPTED
        assert len(result.submission.documents_uploaded) >= 3

        # Petition should be advanced
        assert p.status == PetitionStatus.HEARING_SCHEDULED
        assert p.hearing_date is not None

    def test_submit_efiling_manual_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))
        p = _make_petition("botetourt")  # No e-filing
        generate_all_forms(p)

        result = submit_efiling(p)

        assert result.success is False
        assert result.method == "manual_required"
        assert "does not accept e-filing" in result.message

    def test_submit_sets_case_number(self, tmp_path, monkeypatch):
        monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))
        p = _make_petition("roanoke city")
        generate_all_forms(p)

        result = submit_efiling(p)
        assert result.submission.case_number.startswith("CL")
        assert result.submission.filing_fee_paid == 53.00

    def test_poll_filing_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))
        p = _make_petition("roanoke city")
        generate_all_forms(p)

        result = submit_efiling(p)
        submission = result.submission

        # Poll again — should still be accepted
        updated = poll_filing_status(submission, p)
        assert updated.status == EFilingStatus.ACCEPTED


# ---------------------------------------------------------------------------
# Web integration
# ---------------------------------------------------------------------------

class TestEFilingWebIntegration:
    """Test that the web UI auto-efiles for eligible courts."""

    @pytest.fixture()
    def app(self):
        from va_name_change.web import create_app, store
        app = create_app()
        app.config["TESTING"] = True
        store._store.clear()
        yield app

    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def _run_intake(self, client, monkeypatch, tmp_path, county="roanoke city",
                    city="Roanoke", zip_code="24016"):
        monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))
        client.post("/intake/step1", data={
            "current_name": "John Smith",
            "desired_name": "Jane Smith",
            "reason": "Personal preference",
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
        return location.split("/petition/")[1].split("/")[0]

    def test_efiling_court_auto_files(self, client, monkeypatch, tmp_path):
        """Roanoke City accepts e-filing — petition should be auto-filed."""
        from va_name_change.web import store
        pid = self._run_intake(client, monkeypatch, tmp_path, county="roanoke city")
        petition = store.get(pid)

        # Should have been e-filed and advanced past FILED
        assert petition.status in (PetitionStatus.FILED, PetitionStatus.HEARING_SCHEDULED)
        assert petition.case_number is not None
        assert petition.efiling_confirmation is not None
        assert petition.efiling_envelope_id is not None

    def test_efiling_court_gets_hearing_date(self, client, monkeypatch, tmp_path):
        """E-filed petition should have hearing date assigned automatically."""
        from va_name_change.web import store
        pid = self._run_intake(client, monkeypatch, tmp_path, county="roanoke city")
        petition = store.get(pid)

        assert petition.hearing_date is not None
        assert petition.status == PetitionStatus.HEARING_SCHEDULED

    def test_non_efiling_court_manual(self, client, monkeypatch, tmp_path):
        """Botetourt doesn't accept e-filing — should get manual instructions."""
        from va_name_change.web import store
        pid = self._run_intake(client, monkeypatch, tmp_path, county="botetourt",
                               city="Fincastle", zip_code="24090")
        petition = store.get(pid)

        # Should be filed (via prepare_filing) but no e-filing metadata
        assert petition.status == PetitionStatus.FILED
        assert petition.efiling_confirmation is None
        assert petition.case_number is None

    def test_dashboard_shows_efiling_status(self, client, monkeypatch, tmp_path):
        """Dashboard should show e-filing confirmation for e-filed petitions."""
        pid = self._run_intake(client, monkeypatch, tmp_path, county="roanoke city")
        resp = client.get(f"/petition/{pid}/dashboard")

        assert resp.status_code == 200
        assert b"E-Filing Confirmed" in resp.data
        assert b"Case Number" in resp.data
        assert b"VJEFS Envelope" in resp.data

    def test_dashboard_shows_manual_for_non_efiling(self, client, monkeypatch, tmp_path):
        """Dashboard should show manual filing instructions for non-e-filing courts."""
        pid = self._run_intake(client, monkeypatch, tmp_path, county="botetourt",
                               city="Fincastle", zip_code="24090")
        resp = client.get(f"/petition/{pid}/dashboard")

        assert resp.status_code == 200
        assert b"E-Filing Confirmed" not in resp.data
        assert b"Filing Instructions" in resp.data

    def test_efiling_full_end_to_end(self, client, monkeypatch, tmp_path):
        """Full flow: intake -> auto-efile -> hearing outcome -> post-decree -> complete."""
        from va_name_change.web import store
        pid = self._run_intake(client, monkeypatch, tmp_path, county="roanoke city")
        petition = store.get(pid)

        # After intake: auto-efiled, hearing scheduled
        assert petition.status == PetitionStatus.HEARING_SCHEDULED
        assert petition.case_number is not None

        # Record hearing outcome: granted
        client.post(f"/petition/{pid}/milestone", data={
            "action": "hearing_outcome",
            "outcome": "granted",
        })

        # Dashboard should show post-decree
        resp = client.get(f"/petition/{pid}/dashboard")
        assert b"Post-Decree Updates" in resp.data

        # Mark all agencies complete
        petition = store.get(pid)
        for u in petition.downstream_updates:
            client.post(f"/petition/{pid}/post-decree/complete", data={
                "agency": u.agency,
            }, headers={"Referer": f"/petition/{pid}/dashboard"})

        petition = store.get(pid)
        assert petition.status == PetitionStatus.COMPLETED
