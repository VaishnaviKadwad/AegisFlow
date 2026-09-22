"""
auth/service.py — High-level login/register/OTP orchestration for the UI.

Flow implemented:

  REGISTER
    username + email + password -> account created (password hashed & salted)

  LOGIN (step 1 — password)
    email + password checked against the store.
    On success: an OTP is generated, hashed, stored server-side, and
    emailed to the user's registered address.

  LOGIN (step 2 — OTP)
    user enters the 6-digit code from their email.
    On success: session is marked authenticated.

The UI layer (ui/app.py) only talks to this module — it never touches
auth/store.py, auth/otp.py or auth/mailer.py directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import store as user_store
from . import otp as otp_service
from . import mailer


@dataclass
class LoginStartResult:
    ok: bool
    message: str
    dev_otp: Optional[str] = None   # only populated when SMTP isn't configured


def register_user(username: str, email: str, password: str, confirm_password: str) -> LoginStartResult:
    if password != confirm_password:
        return LoginStartResult(ok=False, message="Passwords do not match.")
    try:
        user_store.create_user(username, email, password)
    except ValueError as exc:
        return LoginStartResult(ok=False, message=str(exc))
    return LoginStartResult(ok=True, message="Account created. You can now log in.")


def start_login(email: str, password: str) -> LoginStartResult:
    """Verify the password, then issue + email an OTP."""
    email = user_store.normalize_email(email)

    if not user_store.is_valid_email(email):
        return LoginStartResult(ok=False, message="Enter a valid email address.")

    user = user_store.authenticate(email, password)
    if not user:
        return LoginStartResult(ok=False, message="Incorrect email or password.")

    try:
        code = otp_service.issue_otp(email, purpose="login")
    except otp_service.OtpError as exc:
        return LoginStartResult(ok=False, message=str(exc))

    result = mailer.send_otp_email(email, code, purpose="login")

    if result.sent:
        return LoginStartResult(ok=True, message=result.detail)
    if result.dev_mode:
        return LoginStartResult(
            ok=True,
            message="SMTP not configured — verification code generated for local testing.",
            dev_otp=code,
        )
    # SMTP was configured but sending failed — don't leave a code the user can't receive.
    otp_service.clear_otp(email)
    return LoginStartResult(ok=False, message=result.detail)


def resend_login_otp(email: str) -> LoginStartResult:
    return start_login_otp_only(email)


def start_login_otp_only(email: str) -> LoginStartResult:
    """Re-issue an OTP without re-checking the password (used for 'resend code')."""
    email = user_store.normalize_email(email)
    try:
        code = otp_service.issue_otp(email, purpose="login")
    except otp_service.OtpError as exc:
        return LoginStartResult(ok=False, message=str(exc))

    result = mailer.send_otp_email(email, code, purpose="login")
    if result.sent:
        return LoginStartResult(ok=True, message=result.detail)
    if result.dev_mode:
        return LoginStartResult(ok=True, message="New code generated for local testing.", dev_otp=code)
    otp_service.clear_otp(email)
    return LoginStartResult(ok=False, message=result.detail)


def complete_login(email: str, code: str) -> LoginStartResult:
    email = user_store.normalize_email(email)
    try:
        otp_service.verify_otp(email, code)
    except otp_service.OtpError as exc:
        return LoginStartResult(ok=False, message=str(exc))

    user = user_store.get_user(email)
    username = user["username"] if user else email
    return LoginStartResult(ok=True, message=f"Welcome back, {username}!")
