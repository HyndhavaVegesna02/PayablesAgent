"""GET/POST /login and POST /logout (TDD Part 2, "HTTP routes": anyone)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from app.web.app import render
from app.web.auth import (
    LOGIN_CSRF_COOKIE,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    WRONG_LOGIN,
    check_csrf,
    cookie_args,
    db,
    new_csrf,
    read_session,
    same_token,
    session_cookie,
    verify_password,
)

router = APIRouter()


def _login_page(request: Request, message: str | None = None, status: int = 200) -> Response:
    token = new_csrf()
    response = render(request, "login.html", {"csrf_token": token, "message": message}, status=status)
    response.set_cookie(LOGIN_CSRF_COOKIE, token, max_age=3600, **cookie_args(request))
    return response


@router.get("/login")
def login_page(request: Request) -> Response:
    return _login_page(request)


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(db),
) -> Response:
    expected = request.cookies.get(LOGIN_CSRF_COOKIE, "")
    if not expected or not same_token(csrf_token, expected):
        return _login_page(request, "The form expired. Please try again.", status=403)
    user = verify_password(conn, email, password)
    if user is None:
        return _login_page(request, WRONG_LOGIN, status=401)
    response = RedirectResponse("/" if user.role == "owner" else "/add", status_code=303)
    response.set_cookie(SESSION_COOKIE, session_cookie(request, user.id), max_age=SESSION_MAX_AGE,
                        **cookie_args(request))
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    # With a session, logging out needs its CSRF token like any POST, so another
    # site cannot log the owner out; with none, there is nothing to end.
    session = read_session(request)
    if session is not None:
        request.state.csrf = session.get("csrf", "")
        await check_csrf(request)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
