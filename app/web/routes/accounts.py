"""Accounts: GET /accounts, POST /accounts/{id}/confirm-balance, and the two
routes whose backend lands with CHG-007: POST /documents/{id}/unlock and
POST /parties/{id}/bank-change (TDD Part 2, "HTTP routes"; batch 3 plan,
CHG-006 S5, Q5)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.web import actions, repo
from app.web.app import render
from app.web.auth import User, db, owner_only
from app.web.routes._common import done, form_values

router = APIRouter()


def accounts_page(request: Request, conn: sqlite3.Connection, user: User, *, errors: dict | None = None,
                  status: int = 200):
    return render(request, "accounts.html", {"accounts": repo.accounts(conn, user.business_id),
                                             "errors": errors or {}}, status=status)


@router.get("/accounts")
def accounts(request: Request, user: User = Depends(owner_only), conn: sqlite3.Connection = Depends(db)):
    return accounts_page(request, conn, user)


@router.post("/accounts/{account_id}/confirm-balance")
async def confirm_balance(account_id: int, request: Request, user: User = Depends(owner_only),
                          conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    try:
        actions.confirm_balance(conn, user, account_id, str(values.get("amount", "")),
                                clock=request.app.state.clock)
    except actions.FieldErrors as e:
        return accounts_page(request, conn, user, errors={account_id: e.errors["amount"]}, status=422)
    return done(request, "/accounts")


@router.post("/documents/{document_id}/unlock")
async def unlock(document_id: int, request: Request, user: User = Depends(owner_only),
                 conn: sqlite3.Connection = Depends(db)):
    # The password field is never read into a variable, logged or traced:
    # there is no locked statement to use it on until CHG-007.
    doc = repo.document(conn, user.business_id, document_id)
    if doc["status"] != "LOCKED":
        raise actions.Refused("There is nothing to unlock: this document is not a locked statement.")
    raise actions.Refused("Unlocking statements comes with a later change (CHG-007).")


@router.post("/parties/{party_id}/bank-change")
async def bank_change(party_id: int, request: Request, user: User = Depends(owner_only),
                      conn: sqlite3.Connection = Depends(db)):
    party = repo.party(conn, user.business_id, party_id)
    if party["bank_status"] != "change_pending":
        raise actions.Refused("There is no pending bank change for this vendor.")
    raise actions.Refused("Approving bank changes comes with a later change (CHG-007).")
