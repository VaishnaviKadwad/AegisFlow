"""
auth/mailer.py — Sends OTP codes by email over SMTP.

.env settings:
    SMTP_HOST       e.g. smtp.gmail.com
    SMTP_PORT       587 (STARTTLS) or 465 (SSL)
    SMTP_USER       mailbox address
    SMTP_PASSWORD   app password (Gmail: App Password, not normal password)
    SMTP_FROM       From header (defaults to SMTP_USER)
    SMTP_USE_TLS    true/false — used for port 587 STARTTLS

If SMTP is not configured → DEV MODE (OTP shown in UI, no email).
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass
class MailResult:
    sent: bool
    dev_mode: bool
    detail: str = ""


def _smtp_config() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or "587"),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_addr": (
            os.getenv("SMTP_FROM", "").strip()
            or os.getenv("SMTP_USER", "").strip()
        ),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").strip().lower() != "false",
    }


def is_smtp_configured() -> bool:
    cfg = _smtp_config()
    return bool(cfg["host"] and cfg["user"] and cfg["password"])


def _build_message(to_email: str, from_addr: str, otp: str, purpose: str) -> MIMEText:
    action = "verify your login" if purpose == "login" else "verify your account"
    body = (
        f"Your AegisFlow verification code is: {otp}\n\n"
        f"Use this code to {action}. It expires in 5 minutes.\n"
        f"If you did not request this, you can safely ignore this email.\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"AegisFlow security code: {otp}"
    msg["From"] = from_addr
    msg["To"] = to_email
    return msg


def _send_ssl(cfg: dict, msg: MIMEText, to_email: str) -> None:
    """Port 465 — implicit SSL."""
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20, context=context) as server:
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from_addr"], [to_email], msg.as_string())


def _send_starttls(cfg: dict, msg: MIMEText, to_email: str) -> None:
    """Port 587 — plain then STARTTLS."""
    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
        server.ehlo()
        if cfg["use_tls"]:
            server.starttls(context=context)
            server.ehlo()
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from_addr"], [to_email], msg.as_string())


def send_otp_email(to_email: str, otp: str, purpose: str = "login") -> MailResult:
    cfg = _smtp_config()

    if not is_smtp_configured():
        return MailResult(
            sent=False,
            dev_mode=True,
            detail="SMTP not configured — showing code in-app for local testing.",
        )

    msg = _build_message(to_email, cfg["from_addr"], otp, purpose)
    port = cfg["port"]
    errors: list[str] = []

    # Prefer method matching the port; fall back to the other if needed
    if port == 465:
        try:
            _send_ssl(cfg, msg, to_email)
            return MailResult(sent=True, dev_mode=False, detail=f"Code sent to {to_email}.")
        except Exception as exc:
            errors.append(f"SSL/465: {exc}")
        try:
            cfg587 = {**cfg, "port": 587, "use_tls": True}
            _send_starttls(cfg587, msg, to_email)
            return MailResult(sent=True, dev_mode=False, detail=f"Code sent to {to_email} (via 587).")
        except Exception as exc:
            errors.append(f"STARTTLS/587: {exc}")
    else:
        # 587 or other — try STARTTLS first, then SSL on 465
        try:
            _send_starttls(cfg, msg, to_email)
            return MailResult(sent=True, dev_mode=False, detail=f"Code sent to {to_email}.")
        except Exception as exc:
            errors.append(f"STARTTLS/{port}: {exc}")
        try:
            cfg465 = {**cfg, "port": 465}
            _send_ssl(cfg465, msg, to_email)
            return MailResult(sent=True, dev_mode=False, detail=f"Code sent to {to_email} (via 465 SSL).")
        except Exception as exc:
            errors.append(f"SSL/465: {exc}")

    return MailResult(
        sent=False,
        dev_mode=False,
        detail="Failed to send email: " + " | ".join(errors),
    )
