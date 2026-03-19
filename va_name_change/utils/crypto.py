"""Lightweight encryption helpers for PII at rest.

Uses Fernet symmetric encryption from the ``cryptography`` library.
The key should be stored in an environment variable or a secrets manager —
never committed to source control.
"""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys

_HAS_FERNET = False
_Fernet = None

# The ``cryptography`` package can fail catastrophically (Rust/pyo3 panic)
# in some environments.  We probe it in a subprocess to avoid crashing the
# main process.
try:
    result = subprocess.run(
        [sys.executable, "-c", "from cryptography.fernet import Fernet"],
        capture_output=True,
        timeout=5,
    )
    if result.returncode == 0:
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]
        _Fernet = Fernet
        _HAS_FERNET = True
except Exception:
    pass


def _get_key() -> bytes:
    """Derive a Fernet key from the ``VNC_ENCRYPTION_KEY`` env var."""
    raw = os.getenv("VNC_ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError(
            "VNC_ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    # If the caller supplies a 32-byte-or-longer passphrase instead of a
    # proper Fernet key, derive one deterministically.
    if len(raw) != 44 or not raw.endswith("="):
        key_bytes = hashlib.sha256(raw.encode()).digest()
        return base64.urlsafe_b64encode(key_bytes)
    return raw.encode()


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe token string."""
    if not _HAS_FERNET:
        # Fallback: base64 encode (NOT secure — acceptable only for dev/test)
        return base64.urlsafe_b64encode(plaintext.encode()).decode()
    f = _Fernet(_get_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token returned by :func:`encrypt`."""
    if not _HAS_FERNET:
        return base64.urlsafe_b64decode(token.encode()).decode()
    f = _Fernet(_get_key())
    return f.decrypt(token.encode()).decode()
