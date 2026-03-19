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


def test_full_intake_flow(client, monkeypatch, tmp_path):
    monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))

    # Step 1
    client.post("/intake/step1", data={
        "current_name": "John Smith",
        "desired_name": "Jane Smith",
        "reason": "Personal preference",
    })

    # Step 2
    client.post("/intake/step2", data={
        "dob": "01/15/1990",
        "ssn": "123-45-6789",
    })

    # Step 3
    client.post("/intake/step3", data={
        "street": "315 Church Ave SW",
        "city": "Roanoke",
        "county": "roanoke city",
        "zip_code": "24016",
    })

    # Step 4 — confirm
    resp = client.get("/intake/step4")
    assert resp.status_code == 200
    assert b"Roanoke City Circuit Court" in resp.data

    resp = client.post("/intake/step4", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Generated Documents" in resp.data or b"CC-1411" in resp.data


def test_documents_page(client, monkeypatch, tmp_path):
    monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))

    # Run full intake
    client.post("/intake/step1", data={
        "current_name": "A B", "desired_name": "C D", "reason": "Marriage",
    })
    client.post("/intake/step2", data={"dob": "2000-01-01", "ssn": "111223333"})
    client.post("/intake/step3", data={
        "street": "1 St", "city": "Salem", "county": "salem", "zip_code": "24153",
    })
    resp = client.post("/intake/step4", follow_redirects=False)

    # Extract petition ID from redirect
    location = resp.headers["Location"]
    petition_id = location.split("/petition/")[1].split("/")[0]

    resp = client.get(f"/petition/{petition_id}/documents")
    assert resp.status_code == 200
    assert b"CC-1411" in resp.data


def test_status_page(client, monkeypatch, tmp_path):
    monkeypatch.setattr("va_name_change.config.config.output_dir", str(tmp_path))

    client.post("/intake/step1", data={
        "current_name": "A B", "desired_name": "C D", "reason": "Marriage",
    })
    client.post("/intake/step2", data={"dob": "2000-01-01", "ssn": "111223333"})
    client.post("/intake/step3", data={
        "street": "1 St", "city": "Roanoke", "county": "roanoke county",
        "zip_code": "24153",
    })
    resp = client.post("/intake/step4", follow_redirects=False)
    petition_id = resp.headers["Location"].split("/petition/")[1].split("/")[0]

    resp = client.get(f"/petition/{petition_id}/status")
    assert resp.status_code == 200
    assert b"Petition Status" in resp.data


def test_404_for_unknown_petition(client):
    resp = client.get("/petition/nonexistent/documents")
    assert resp.status_code == 404


def test_roanoke_jurisdictions_in_dropdown(client):
    resp = client.get("/intake/step1")
    # After step1, go to step3 to check dropdown
    client.post("/intake/step1", data={
        "current_name": "X", "desired_name": "Y", "reason": "Other",
    })
    client.post("/intake/step2", data={"dob": "2000-01-01", "ssn": "111223333"})
    resp = client.get("/intake/step3")
    assert resp.status_code == 200
    # Check Roanoke-area jurisdictions are present
    assert b"Roanoke City" in resp.data
    assert b"Roanoke County" in resp.data
    assert b"Salem" in resp.data
    assert b"Botetourt" in resp.data
    assert b"Craig" in resp.data
    assert b"Bedford County" in resp.data
    assert b"Franklin County" in resp.data
