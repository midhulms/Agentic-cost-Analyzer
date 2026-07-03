# Lightweight login + free-usage-quota system. Author: Cryzal
#
# Deliberately dependency-free (uses only stdlib hashlib/secrets) so it adds
# zero new packages to requirements.txt. Good enough for a portfolio/demo
# app; if this ever needs to be production-grade for real paying users,
# swap hash_password()/verify_password() for bcrypt or argon2 and wire
# mark_paid() up to a real Stripe webhook instead of calling it directly.
import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings

FREE_USES = 5

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    free_uses_remaining INTEGER NOT NULL DEFAULT 5,
    is_paid INTEGER NOT NULL DEFAULT 0,
    created_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_ts REAL NOT NULL
);
"""


@contextmanager
def get_conn():
    db_dir = os.path.dirname(settings.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_auth_db() -> None:
    with get_conn() as conn:
        conn.executescript(AUTH_SCHEMA)
        conn.commit()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def create_user(email: str, password: str) -> dict:
    email = email.strip().lower()
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, salt, free_uses_remaining, is_paid, created_ts) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (email, password_hash, salt, FREE_USES, time.time()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("An account with that email already exists.")
        user_id = cur.lastrowid
    return _user_row_to_dict((user_id, email, FREE_USES, 0))


def verify_user(email: str, password: str) -> Optional[dict]:
    email = email.strip().lower()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, salt, free_uses_remaining, is_paid FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if row is None:
        return None
    user_id, db_email, password_hash, salt, free_uses_remaining, is_paid = row
    if _hash_password(password, salt) != password_hash:
        return None
    return _user_row_to_dict((user_id, db_email, free_uses_remaining, is_paid))


def _user_row_to_dict(row) -> dict:
    user_id, email, free_uses_remaining, is_paid = row
    return {
        "id": user_id,
        "email": email,
        "free_uses_remaining": free_uses_remaining,
        "is_paid": bool(is_paid),
    }


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_ts) VALUES (?, ?, ?)",
            (token, user_id, time.time()),
        )
        conn.commit()
    return token


def get_user_by_token(token: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u.id, u.email, u.free_uses_remaining, u.is_paid "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
    if row is None:
        return None
    return _user_row_to_dict(row)


def consume_free_use(user_id: int) -> dict:
    """Call right before running a paid action. Returns
    {"allowed": bool, "free_uses_remaining": int, "is_paid": bool}.
    Paid users are always allowed and never decremented."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT free_uses_remaining, is_paid FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return {"allowed": False, "free_uses_remaining": 0, "is_paid": False}
        free_uses_remaining, is_paid = row
        if is_paid:
            return {"allowed": True, "free_uses_remaining": free_uses_remaining, "is_paid": True}
        if free_uses_remaining <= 0:
            return {"allowed": False, "free_uses_remaining": 0, "is_paid": False}
        new_remaining = free_uses_remaining - 1
        conn.execute("UPDATE users SET free_uses_remaining = ? WHERE id = ?", (new_remaining, user_id))
        conn.commit()
        return {"allowed": True, "free_uses_remaining": new_remaining, "is_paid": False}


def mark_paid(user_id: int) -> dict:
    """Mock 'upgrade' -- flips is_paid to true with no real payment taken.
    Wire this to a Stripe webhook handler (checkout.session.completed) in
    production instead of calling it directly from the client."""
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_paid = 1 WHERE id = ?", (user_id,))
        conn.commit()
        row = conn.execute(
            "SELECT id, email, free_uses_remaining, is_paid FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return _user_row_to_dict(row)


def require_user(authorization: str = Header(default=None)) -> dict:
    """FastAPI dependency: reads `Authorization: Bearer <token>`, returns
    the user dict, or raises 401 if missing/invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header. Log in first.")
    token = authorization.removeprefix("Bearer ").strip()
    user = get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Log in again.")
    return user
