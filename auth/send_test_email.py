"""
auth/send_test_email.py — quick standalone check that your SMTP settings
in .env actually deliver an email, without going through the Streamlit UI.

Usage (from the AegisFlow/ folder):
    python auth/send_test_email.py you@example.com
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auth import mailer  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("Usage: python auth/send_test_email.py you@example.com")
        sys.exit(1)

    to_email = sys.argv[1]

    print("SMTP configured:", mailer.is_smtp_configured())
    cfg = mailer._smtp_config()
    safe_cfg = {**cfg, "password": "***" if cfg["password"] else ""}
    print("Config read from .env:", safe_cfg)

    result = mailer.send_otp_email(to_email, "123456", purpose="login")
    print("\n--- Result ---")
    print("sent:     ", result.sent)
    print("dev_mode: ", result.dev_mode)
    print("detail:   ", result.detail)


if __name__ == "__main__":
    main()
