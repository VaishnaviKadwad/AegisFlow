"""
auth/store.py — Local user store for AegisFlow login.

Users are persisted as JSON at auth/users.json. Passwords are never stored
in plaintext: each password is hashed with PBKDF2-HMAC-SHA256 using a
per-user random salt (stdlib only, no extra dependency required).

This is intentionally a simple, file-based store suitable for a hackathon
demo / small deployment. Swap `load_users` / `save_users` for a real
database in production.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import threading
from pathlib import Path
from typing import Optional

USERS_FILE = Path(__file__).resolve().parent / "users.json"
_LOCK = threading.Lock()

PBKDF2_ITERATIONS = 260_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _read_raw() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_users() -> dict:
    """Return {email: user_record} dict."""
    with _LOCK:
        return _read_raw()


def save_users(users: dict) -> None:
    with _LOCK:
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = USERS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
        tmp.replace(USERS_FILE)


def _hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return dk.hex()


def hash_new_password(password: str) -> dict:
    salt = os.urandom(16)
    return {"salt": salt.hex(), "hash": _hash_password(password, salt)}


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    candidate = _hash_password(password, salt)
    return hmac.compare_digest(candidate, hash_hex)


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user(email: str) -> Optional[dict]:
    users = load_users()
    return users.get(normalize_email(email))


def create_user(username: str, email: str, password: str) -> dict:
    """Create and persist a new user. Raises ValueError on bad input."""
    email = normalize_email(email)
    username = username.strip()

    if not username:
        raise ValueError("Username is required.")
    if not is_valid_email(email):
        raise ValueError("Enter a valid email address.")
    password = password.strip()
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    users = load_users()
    if email in users:
        raise ValueError("An account with this email already exists.")

    creds = hash_new_password(password)
    record = {
        "username": username,
        "email": email,
        "salt": creds["salt"],
        "hash": creds["hash"],
        "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
    users[email] = record
    save_users(users)
    return record


def authenticate(email: str, password: str) -> Optional[dict]:
    """Return the user record if email/password match, else None."""
    password = password.strip()
    user = get_user(email)
    if not user:
        return None
    if verify_password(password, user["salt"], user["hash"]):
        return user
    return None
