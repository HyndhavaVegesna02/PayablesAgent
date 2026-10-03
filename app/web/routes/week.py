"""This week: GET /, POST /plans/{run_id}/approve, POST /payables/{id}/mark-paid
(TDD Part 2, "HTTP routes"; batch 3 plan, CHG-006 S2 and S4)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.domain.states import StaleVersion, VersionRequired
from app.web import actions, repo
from app.web.app import render
from app.web.auth import User, db, owner_only
from app.web.routes._common import done, form_values, int_or_none

router = APIRouter()


def week_page(request: Request, conn: sqlite3.Connection, user: User, *, message: str | None = None,
              status: int = 200) -> Response:
    return render(request, "week.html", {
        "view": repo.plan_view(conn, user.business_id),
        "business": repo.business(conn, user.business_id),
        "awaiting": repo.awaiting_payment(conn, user.business_id),
        "message": message,
    }, status=status)


def stale_page(request: Request, conn: sqlite3.Connection, user: User, message: str) -> Response:
    """The refusal page for a stale plan: replanned first if today's inputs no
    longer match the current run, so its figures are current and approvable."""
    actions.refresh_if_stale(conn, user, clock=request.app.state.clock)
    return week_page(request, conn, user, message=message, status=409)


@router.get("/")
def this_week(request: Request, user: User = Depends(owner_only), conn: sqlite3.Connection = Depends(db)):
    return week_page(request, conn, user)


@router.post("/plans/{run_id}/approve")
async def approve(run_id: int, request: Request, user: User = Depends(owner_only),
                  conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    versions = {
        int(k.removeprefix("version_")): v
        for k, raw in values.items() if k.startswith("version_") and k[8:].isdigit()
        if (v := int_or_none(raw)) is not None
    }
    try:
        actions.approve(conn, user, run_id, versions, clock=request.app.state.clock)
    except actions.Stale as e:
        return stale_page(request, conn, user, str(e))
    return done(request, "/")


@router.post("/payables/{payable_id}/mark-paid")
async def mark_paid(payable_id: int, request: Request, user: User = Depends(owner_only),
                    conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    try:
        actions.mark_paid(conn, user, payable_id, int_or_none(values.get("version")),
                          clock=request.app.state.clock)
    except StaleVersion:
        return week_page(request, conn, user, message="This bill changed since you opened the page. "
                         "Here is the current plan.", status=409)
    except VersionRequired:
        return week_page(request, conn, user, message="The form was missing the bill's version. "
                         "Use the Mark paid button on this page.", status=409)
    return done(request, "/")
