"""VJEFS (Virginia Judicial Electronic Filing System) client.

Handles authentication, document submission, payment, and status polling
against the Virginia court e-filing system.

In production mode (VNC_EFILING_MODE=live), this submits real filings.
In simulator mode (default), it simulates the VJEFS API for development
and testing, returning realistic responses with deterministic timing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class EFilingStatus(Enum):
    """Status of an e-filing submission."""
    PENDING = "pending"                # Queued, not yet submitted
    SUBMITTED = "submitted"            # Sent to VJEFS
    ACCEPTED = "accepted"              # Court accepted the filing
    REJECTED = "rejected"              # Court rejected (missing docs, etc.)
    PAYMENT_PENDING = "payment_pending"  # Awaiting fee payment
    PAYMENT_COMPLETE = "payment_complete"  # Fee paid
    FAILED = "failed"                  # System error


@dataclass
class EFilingSubmission:
    """Tracks a single e-filing submission to VJEFS."""
    submission_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    petition_id: str = ""
    court_fips: str = ""
    case_number: Optional[str] = None
    status: EFilingStatus = EFilingStatus.PENDING
    envelope_id: Optional[str] = None    # VJEFS envelope tracking ID
    confirmation_code: Optional[str] = None
    filing_fee_paid: float = 0.0
    submitted_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    rejected_reason: Optional[str] = None
    hearing_date: Optional[date] = None
    documents_uploaded: list[str] = field(default_factory=list)
    payment_transaction_id: Optional[str] = None


@dataclass
class VJEFSCredentials:
    """Credentials for the VJEFS e-filing portal."""
    username: str = ""
    password: str = ""
    firm_id: str = ""            # Optional firm/organization ID
    api_key: str = ""            # API key for programmatic access
    payment_account_id: str = ""  # Pre-registered payment account


# ---------------------------------------------------------------------------
# VJEFS API Client (production)
# ---------------------------------------------------------------------------

_VJEFS_BASE_URL = "https://efile.courts.state.va.us/api/v1"


class VJEFSError(Exception):
    """Raised when the VJEFS API returns an error."""
    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class VJEFSClient:
    """HTTP client for the Virginia Judicial Electronic Filing System.

    Implements the VJEFS REST API for:
    - Authentication (session token)
    - Envelope creation (grouping documents for a single filing)
    - Document upload (PDF attachments)
    - Payment submission (filing fees)
    - Filing submission (final commit)
    - Status polling (acceptance, case number, hearing date)
    """

    def __init__(self, credentials: VJEFSCredentials, base_url: str = _VJEFS_BASE_URL):
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self._session_token: Optional[str] = None
        self._token_expires: float = 0

    # -- Auth ---------------------------------------------------------------

    def _ensure_session(self) -> str:
        """Obtain or refresh the VJEFS session token."""
        if self._session_token and time.time() < self._token_expires:
            return self._session_token

        payload = json.dumps({
            "username": self.credentials.username,
            "password": self.credentials.password,
            "api_key": self.credentials.api_key,
        }).encode()

        resp = self._post("/auth/token", payload, authenticated=False)
        self._session_token = resp["token"]
        self._token_expires = time.time() + resp.get("expires_in", 3600) - 60
        return self._session_token

    # -- HTTP helpers -------------------------------------------------------

    def _request(self, method: str, path: str, body: bytes | None = None,
                 authenticated: bool = True, content_type: str = "application/json") -> dict:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": content_type, "Accept": "application/json"}

        if authenticated:
            token = self._ensure_session()
            headers["Authorization"] = f"Bearer {token}"

        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except HTTPError as e:
            body_text = e.read().decode() if e.fp else ""
            raise VJEFSError(
                f"VJEFS API error: {e.code} {e.reason}",
                status_code=e.code,
                response_body=body_text,
            ) from e
        except URLError as e:
            raise VJEFSError(f"VJEFS connection error: {e.reason}") from e

    def _post(self, path: str, body: bytes | None = None,
              authenticated: bool = True) -> dict:
        return self._request("POST", path, body, authenticated)

    def _get(self, path: str) -> dict:
        return self._request("GET", path)

    def _upload_file(self, path: str, filepath: str, doc_type: str) -> dict:
        """Upload a PDF file to VJEFS using multipart form data."""
        boundary = uuid.uuid4().hex
        content_type = f"multipart/form-data; boundary={boundary}"

        with open(filepath, "rb") as f:
            file_data = f.read()

        filename = os.path.basename(filepath)
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document_type"\r\n\r\n'
            f"{doc_type}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

        return self._request("POST", path, body, content_type=content_type)

    # -- Filing operations --------------------------------------------------

    def create_envelope(self, court_fips: str, case_type: str = "NAME_CHANGE") -> dict:
        """Create a new filing envelope (container for documents)."""
        payload = json.dumps({
            "court_fips": court_fips,
            "case_type": case_type,
            "case_category": "CIVIL",
            "filing_type": "INITIAL",
        }).encode()
        return self._post("/envelopes", payload)

    def upload_document(self, envelope_id: str, filepath: str,
                        doc_type: str = "PETITION") -> dict:
        """Upload a document to an existing envelope."""
        return self._upload_file(
            f"/envelopes/{envelope_id}/documents",
            filepath,
            doc_type,
        )

    def submit_payment(self, envelope_id: str, amount: float) -> dict:
        """Submit filing fee payment for an envelope."""
        payload = json.dumps({
            "envelope_id": envelope_id,
            "amount": amount,
            "payment_account_id": self.credentials.payment_account_id,
            "payment_type": "FILING_FEE",
        }).encode()
        return self._post(f"/envelopes/{envelope_id}/payment", payload)

    def submit_filing(self, envelope_id: str) -> dict:
        """Commit the envelope — submits filing to the court."""
        return self._post(f"/envelopes/{envelope_id}/submit")

    def get_filing_status(self, envelope_id: str) -> dict:
        """Poll for the current status of a submitted filing."""
        return self._get(f"/envelopes/{envelope_id}/status")

    def get_case_details(self, envelope_id: str) -> dict:
        """Get case details (case number, hearing date) after acceptance."""
        return self._get(f"/envelopes/{envelope_id}/case")


# ---------------------------------------------------------------------------
# Simulator (for development and testing)
# ---------------------------------------------------------------------------

class VJEFSSimulator:
    """Simulates the VJEFS API for development and testing.

    Produces realistic responses with deterministic behavior:
    - Envelopes are created instantly
    - Documents upload succeeds immediately
    - Payment processes in the same call
    - Filing is "accepted" on the next status poll
    - A hearing date is assigned ~6-8 weeks from submission
    """

    def __init__(self) -> None:
        self._envelopes: dict[str, dict] = {}

    def create_envelope(self, court_fips: str, case_type: str = "NAME_CHANGE") -> dict:
        envelope_id = f"ENV-{uuid.uuid4().hex[:10].upper()}"
        self._envelopes[envelope_id] = {
            "envelope_id": envelope_id,
            "court_fips": court_fips,
            "case_type": case_type,
            "status": "CREATED",
            "documents": [],
            "payment_status": "UNPAID",
            "created_at": datetime.utcnow().isoformat(),
            "submitted_at": None,
            "case_number": None,
            "hearing_date": None,
        }
        return {"envelope_id": envelope_id, "status": "CREATED"}

    def upload_document(self, envelope_id: str, filepath: str,
                        doc_type: str = "PETITION") -> dict:
        env = self._envelopes.get(envelope_id)
        if not env:
            raise VJEFSError(f"Envelope {envelope_id} not found", status_code=404)

        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
        doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"

        env["documents"].append({
            "document_id": doc_id,
            "filename": filename,
            "doc_type": doc_type,
            "size_bytes": file_size,
        })

        return {
            "document_id": doc_id,
            "filename": filename,
            "status": "UPLOADED",
        }

    def submit_payment(self, envelope_id: str, amount: float) -> dict:
        env = self._envelopes.get(envelope_id)
        if not env:
            raise VJEFSError(f"Envelope {envelope_id} not found", status_code=404)

        tx_id = f"PAY-{uuid.uuid4().hex[:10].upper()}"
        env["payment_status"] = "PAID"

        return {
            "transaction_id": tx_id,
            "amount": amount,
            "status": "COMPLETED",
        }

    def submit_filing(self, envelope_id: str) -> dict:
        env = self._envelopes.get(envelope_id)
        if not env:
            raise VJEFSError(f"Envelope {envelope_id} not found", status_code=404)

        if env["payment_status"] != "PAID":
            raise VJEFSError("Payment required before submission", status_code=400)

        env["status"] = "SUBMITTED"
        env["submitted_at"] = datetime.utcnow().isoformat()

        # Generate case number (format: CL26-XXXXX for civil cases)
        year = datetime.utcnow().strftime("%y")
        seq = abs(hash(envelope_id)) % 99999
        env["case_number"] = f"CL{year}-{seq:05d}"

        # Assign a hearing date 6-8 weeks out
        hearing = date.today() + timedelta(weeks=7)
        env["hearing_date"] = hearing.isoformat()

        confirmation = hashlib.sha256(envelope_id.encode()).hexdigest()[:12].upper()

        return {
            "envelope_id": envelope_id,
            "status": "SUBMITTED",
            "confirmation_code": confirmation,
            "case_number": env["case_number"],
        }

    def get_filing_status(self, envelope_id: str) -> dict:
        env = self._envelopes.get(envelope_id)
        if not env:
            raise VJEFSError(f"Envelope {envelope_id} not found", status_code=404)

        # Simulate: once submitted, immediately accepted
        status = "ACCEPTED" if env["status"] == "SUBMITTED" else env["status"]

        return {
            "envelope_id": envelope_id,
            "status": status,
            "case_number": env.get("case_number"),
            "hearing_date": env.get("hearing_date"),
            "documents": env["documents"],
        }

    def get_case_details(self, envelope_id: str) -> dict:
        env = self._envelopes.get(envelope_id)
        if not env:
            raise VJEFSError(f"Envelope {envelope_id} not found", status_code=404)

        return {
            "case_number": env.get("case_number"),
            "hearing_date": env.get("hearing_date"),
            "status": "ACCEPTED" if env["status"] == "SUBMITTED" else env["status"],
            "court_fips": env["court_fips"],
        }


# ---------------------------------------------------------------------------
# Factory — returns the right client based on configuration
# ---------------------------------------------------------------------------

def get_vjefs_client() -> VJEFSClient | VJEFSSimulator:
    """Return the appropriate VJEFS client based on VNC_EFILING_MODE.

    - ``live``:  Real VJEFS client (requires credentials)
    - ``sim`` or unset: Simulator for development/testing
    """
    mode = os.getenv("VNC_EFILING_MODE", "sim").lower()

    if mode == "live":
        creds = VJEFSCredentials(
            username=os.environ["VNC_VJEFS_USERNAME"],
            password=os.environ["VNC_VJEFS_PASSWORD"],
            api_key=os.getenv("VNC_VJEFS_API_KEY", ""),
            firm_id=os.getenv("VNC_VJEFS_FIRM_ID", ""),
            payment_account_id=os.environ["VNC_VJEFS_PAYMENT_ACCOUNT"],
        )
        return VJEFSClient(creds)

    return VJEFSSimulator()
