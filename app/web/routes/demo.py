"""POST /demo/time: the owner moves the demo clock forward (batch 3 plan,
PO decision D14). Registered only in demo mode (DEMO_NOW set); outside a
demo the path does not exist (404). Not in the TDD's route table."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from app import demo
from app.web import actions
from app.web.auth import User, db, owner_only
from app.web.routes._common import done, form_values

router = APIRouter()


@router.post("/demo/time")
async def demo_time(request: Request, user: User = Depends(owner_only), conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    try:
        demo.advance(conn, request.app.state.clock, demo.parse_time(str(values.get("to", ""))))
    except ValueError as e:
        raise actions.Refused(f"The demo clock did not move: {e}") from None
    return done(request, "/")
