"""The owner web app (TDD Part 1, "Owner web app"; Part 2, "HTTP routes").
Pages return full HTML; actions are HTMX POSTs that return the part of the
page to swap in. Templates escape everything: Jinja autoescape is on and no
template marks any value safe (tests/test_web_plain_text.py), so text from an
email or the AI is always shown as plain text."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.domain.money import format_inr
from app.domain.states import StaleVersion, TransitionRefused, VersionRequired
from app.planner.plan import format_day
from app.web.actions import FieldErrors, Refused, Stale
from app.web.auth import NotLoggedIn
from app.web.repo import NotFound

HERE = Path(__file__).resolve().parent

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(HERE / "templates"),
    autoescape=True,  # every value is escaped; nothing in app/web marks a value safe
    undefined=jinja2.StrictUndefined,
)
_env.filters["inr"] = format_inr
_env.filters["day"] = format_day
templates = Jinja2Templates(env=_env)


def render(request: Request, name: str, context: dict[str, Any] | None = None, status: int = 200) -> HTMLResponse:
    """A full page, or only its main block for an HTMX request."""
    settings = request.app.state.settings
    ctx = {
        "demo_now": request.app.state.clock.now() if settings.demo_now else None,
        "demo_ai": settings.demo_ai == "fixtures",
        "user": getattr(request.state, "user", None),
        "csrf_token": getattr(request.state, "csrf", ""),
        "partial": request.headers.get("hx-request") == "true",
        **(context or {}),
    }
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def install(app: FastAPI) -> None:
    from app.web.routes import accounts, add, api, attention, login, settings, week

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    for module in (login, week, attention, add, accounts, settings, api):
        app.include_router(module.router)
    if app.state.settings.demo_now:  # D14: the demo clock's form; absent outside a demo
        from app.web.routes import demo

        app.include_router(demo.router)

    @app.exception_handler(NotLoggedIn)
    async def not_logged_in(request: Request, exc: NotLoggedIn) -> Response:
        if request.method == "GET" and not request.url.path.startswith("/api/"):
            return RedirectResponse("/login", status_code=303)
        return Response("Log in first.", status_code=401, media_type="text/plain")

    def plain(request: Request, message: str, status: int) -> Response:
        if request.url.path.startswith("/api/"):
            return Response(message, status_code=status, media_type="text/plain")
        return render(request, "error.html", {"message": message}, status=status)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        return plain(request, str(exc.detail), exc.status_code)

    @app.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound) -> Response:
        return plain(request, "Not found.", 404)

    @app.exception_handler(Stale)
    @app.exception_handler(Refused)
    async def refused(request: Request, exc: Exception) -> Response:
        return plain(request, str(exc), 409)

    @app.exception_handler(FieldErrors)
    async def field_errors(request: Request, exc: FieldErrors) -> Response:
        return plain(request, " ".join(exc.errors.values()), 422)

    @app.exception_handler(TransitionRefused)
    async def ledger_refused(request: Request, exc: TransitionRefused) -> Response:
        # The writer's own refusal: the record moved on since the page was opened,
        # or the table does not allow this move from its current state.
        if isinstance(exc, (StaleVersion, VersionRequired)):
            return plain(request, "This changed since you opened the page. Reload it and try again.", 409)
        return plain(request, f"This can't be done now: {exc}", 409)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError) -> Response:
        return plain(request, "Something in the request was missing or not readable.", 422)
