"""
auth/otp.py — One-Time Password generation & verification for AegisFlow login.

Design:
- A 6-digit numeric OTP is generated with `secrets` (CSPRNG).
- Only a salted SHA-256 hash of the OTP is kept server-side — never the
  plaintext code — so nothing sensitive leaks if the store is inspected.
- Each OTP has a short expiry window and a limited number of verification
  attempts before it is invalidated (basic brute-force protection).
- A resend cooldown prevents spamming the mail server / mailbox.

State is kept in a process-local dict keyed by email. That's sufficient for
a single-instance Streamlit deployment; swap for Redis / a DB table with a
TTL if you run multiple worker processes.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Optional

OTP_LENGTH = 6
OTP_TTL_SECONDS = 5 * 60          # OTP valid for 5 minutes
RESEND_COOLDOWN_SECONDS = 30      # min gap between resends
MAX_ATTEMPTS = 5                  # wrong guesses allowed before lockout

_lock = threading.Lock()
_store: dict[str, "OtpRecord"] = {}


@dataclass
class OtpRecord:
    salt: str
    otp_hash: str
    created_at: float
    expires_at: float
    attempts: int = 0
    purpose: str = "login"


class OtpError(Exception):
    """Raised for expected, user-facing OTP failures."""


def _hash_otp(code: str, salt: str) -> str:
    return hashlib.sha256((salt + code).encode("utf-8")).hexdigest()


def generate_otp() -> str:
    """Cryptographically-random n-digit numeric code, zero-padded."""
    number = secrets.randbelow(10 ** OTP_LENGTH)
    return str(number).zfill(OTP_LENGTH)


def issue_otp(email: str, purpose: str = "login") -> str:
    """
    Create a new OTP for `email`, store its hash, and return the plaintext
    code so the caller can email it. Enforces the resend cooldown.
    """
    email = email.strip().lower()
    now = time.time()

    with _lock:
        existing = _store.get(email)
        if existing and (now - existing.created_at) < RESEND_COOLDOWN_SECONDS:
            wait = int(RESEND_COOLDOWN_SECONDS - (now - existing.created_at))
            raise OtpError(f"Please wait {wait}s before requesting another code.")

        code = generate_otp()
        salt = secrets.token_hex(8)
        _store[email] = OtpRecord(
            salt=salt,
            otp_hash=_hash_otp(code, salt),
            created_at=now,
            expires_at=now + OTP_TTL_SECONDS,
            attempts=0,
            purpose=purpose,
        )
    return code


def verify_otp(email: str, code: str) -> bool:
    """
    Check `code` against the stored OTP for `email`.
    Raises OtpError with a user-facing message on any failure.
    Returns True and clears the record on success.
    """
    email = email.strip().lower()
    code = (code or "").strip()
    now = time.time()

    with _lock:
        record = _store.get(email)
        if not record:
            raise OtpError("No active code for this email. Request a new one.")

        if now > record.expires_at:
            del _store[email]
            raise OtpError("This code has expired. Request a new one.")

        if record.attempts >= MAX_ATTEMPTS:
            del _store[email]
            raise OtpError("Too many incorrect attempts. Request a new code.")

        if not code.isdigit() or len(code) != OTP_LENGTH:
            record.attempts += 1
            raise OtpError(f"Enter the {OTP_LENGTH}-digit code sent to your email.")

        candidate = _hash_otp(code, record.salt)
        if not secrets.compare_digest(candidate, record.otp_hash):
            record.attempts += 1
            remaining = MAX_ATTEMPTS - record.attempts
            del _store[email]
            if remaining <= 0:
                raise OtpError("Incorrect code. Too many attempts — request a new code.")
            _store[email] = record  # keep counting if attempts remain
            raise OtpError(f"Incorrect code. {remaining} attempt(s) left.")

        # success
        del _store[email]
        return True


def seconds_until_resend(email: str) -> int:
    email = email.strip().lower()
    with _lock:
        record = _store.get(email)
        if not record:
            return 0
        remaining = RESEND_COOLDOWN_SECONDS - (time.time() - record.created_at)
        return max(0, int(remaining))


def clear_otp(email: str) -> None:
    email = email.strip().lower()
    with _lock:
        _store.pop(email, None)
