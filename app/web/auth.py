"""Login, the session cookie, CSRF and the role check (TDD Part 2, "HTTP
routes"; batch 3 plan, CHG-006 S1).

- The session is a signed cookie (itsdangerous) holding the user id and a
  CSRF token: HttpOnly, SameSite=Lax, 12 hours.
- Every POST carries that CSRF token, as a form field or the X-CSRF-Token
  header HTMX sends; a missing or wrong one is a 403.
- The role is checked on the server by a FastAPI dependency on every route
  (`require`), never only in the page.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE = "pa_session"
LOGIN_CSRF_COOKIE = "pa_login_csrf"
SESSION_MAX_AGE = 12 * 3600
SECRET_COMMAND = 'uv run python -c "import secrets; print(secrets.token_urlsafe(32))"'
WRONG_LOGIN = "Wrong email or password."

_hasher = PasswordHasher()


class SessionSecretMissing(RuntimeError):
    pass


def check_secret(secret: str) -> str:
    if not secret.strip():
        raise SessionSecretMissing(
            "SESSION_SECRET is not set. The web app signs its login cookie with it. Generate one with:\n"
            f"    {SECRET_COMMAND}\n"
            "and set SESSION_SECRET=<that value> in .env (or the environment), then start the app again."
        )
    return secret


@dataclass(frozen=True)
class User:
    id: int
    business_id: int
    email: str
    role: str

    @property
    def actor(self) -> str:
        """The ledger writer's actor for this user's owner actions. Helpers make
        no ledger writes (they only submit), so only owners have one."""
        if self.role != "owner":
            raise PermissionError("only an owner acts on the ledger")
        return f"owner:{self.id}"


class NotLoggedIn(Exception):
    """Handled in app.py: a page redirects to /login, an action gets 401."""


def serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(request.app.state.settings.session_secret, salt="pa-session")


def new_csrf() -> str:
    return secrets.token_urlsafe(32)


def session_cookie(request: Request, user_id: int) -> str:
    return serializer(request).dumps({"uid": user_id, "csrf": new_csrf()})


def cookie_args(request: Request) -> dict[str, Any]:
    return {"httponly": True, "samesite": "lax", "secure": request.app.state.settings.cookie_secure, "path": "/"}


def read_session(request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = serializer(request).loads(raw, max_age=SESSION_MAX_AGE)  # SignatureExpired is a BadSignature
    except BadSignature:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("uid"), int) else None


def verify_password(conn: sqlite3.Connection, email: str, password: str) -> User | None:
    row = conn.execute(
        "SELECT id, business_id, email, role, password_hash FROM app_user WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()
    if row is None:
        _hasher.hash(password or "-")  # spend the same time whether or not the email exists
        return None
    try:
        _hasher.verify(row["password_hash"], password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return None
    return User(row["id"], row["business_id"], row["email"], row["role"])


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# --- dependencies ------------------------------------------------------------------


def db(request: Request):
    from app.db.connection import write_connection

    conn = write_connection(request.app.state.settings.database_path, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn: sqlite3.Connection = Depends(db)) -> User:
    session = read_session(request)
    if session is None:
        raise NotLoggedIn()
    row = conn.execute(
        "SELECT id, business_id, email, role FROM app_user WHERE id = ?", (session["uid"],)
    ).fetchone()
    if row is None:
        raise NotLoggedIn()
    request.state.csrf = session.get("csrf", "")
    request.state.user = User(row["id"], row["business_id"], row["email"], row["role"])
    return request.state.user


async def check_csrf(request: Request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    expected = getattr(request.state, "csrf", "")
    sent = request.headers.get("x-csrf-token")
    if sent is None:
        form = await request.form()
        sent = form.get("csrf_token")
    if not expected or not isinstance(sent, str) or not hmac.compare_digest(sent, expected):
        raise HTTPException(403, "The form expired or came from somewhere else. Reload the page and try again.")


def require(*roles: str):
    """Dependency for every route: logged in, one of `roles`, and a valid CSRF
    token on anything that changes state."""

    async def dependency(request: Request, user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "This page is for the business owner.")
        await check_csrf(request)
        return user

    dependency.roles = roles  # read by the route-table test
    return dependency


owner_only = require("owner")
owner_or_helper = require("owner", "helper")
