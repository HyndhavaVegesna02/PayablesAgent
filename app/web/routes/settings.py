"""Settings: GET and POST /settings (owner only; TDD Part 2, "HTTP routes").
A POST changes either the business settings or one bill's priority (it
carries payable_id). Every change goes through the ledger writer as an event
and is followed by the inline replan (batch 3 plan, Q7)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.domain.money import format_inr
from app.web import actions, repo
from app.web.app import render
from app.web.auth import User, db, owner_only
from app.web.routes._common import done, form_values, int_or_none

router = APIRouter()
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def settings_page(request: Request, conn: sqlite3.Connection, user: User, *, values: dict | None = None,
                  errors: dict | None = None, status: int = 200):
    b = repo.business(conn, user.business_id)
    shown = values or {
        "safety_amount": format_inr(b["safety_amount_paise"]),
        "escalation_amount": format_inr(b["escalation_stake_paise"]),
        "horizon_days": str(b["horizon_days"]), "payment_days": b["payment_days"], "language": b["language"],
    }
    return render(request, "settings.html", {
        "v": shown, "e": errors or {}, "days": DAYS, "bills": repo.open_bills(conn, user.business_id),
        "priorities": actions.PRIORITIES,
    }, status=status)


@router.get("/settings")
def settings(request: Request, user: User = Depends(owner_only), conn: sqlite3.Connection = Depends(db)):
    return settings_page(request, conn, user)


@router.post("/settings")
async def change_settings(request: Request, user: User = Depends(owner_only),
                          conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    clock = request.app.state.clock
    try:
        if "payable_id" in values:
            payable_id = int_or_none(values["payable_id"])
            if payable_id is None:
                raise actions.FieldErrors({"priority": "Choose a bill."}, {})
            actions.set_priority(conn, user, payable_id, str(values.get("priority", "")),
                                 int_or_none(values.get("version")), clock=clock)
        else:
            actions.update_settings(conn, user, values, clock=clock)
    except actions.FieldErrors as e:
        shown = None if "payable_id" in values else {"payment_days": "", **e.values}
        return settings_page(request, conn, user, values=shown, errors=e.errors, status=422)
    return done(request, "/settings")
