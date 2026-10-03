"""Needs attention: GET /attention, candidate confirm and reject, shortfall
options and question answers (TDD Part 2, "HTTP routes"; batch 3 plan,
CHG-006 S3 to S5)."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.domain.money import format_inr
from app.web import actions, repo
from app.web.app import render
from app.web.auth import User, db, owner_only
from app.web.routes._common import done, form_values
from app.web.routes.week import stale_page

router = APIRouter()


def attention_page(request: Request, conn: sqlite3.Connection, user: User, *, message: str | None = None,
                   errors: dict[int, dict[str, str]] | None = None, values: dict[int, dict] | None = None,
                   status: int = 200) -> Response:
    run = repo.current_run(conn, user.business_id)
    all_accounts = repo.accounts(conn, user.business_id)
    candidates = repo.waiting_candidates(conn, user.business_id)
    shown = {c["id"]: (values or {}).get(c["id"]) or prefill(c, all_accounts) for c in candidates}
    questions = repo.open_questions(conn, user.business_id)
    for q in questions:
        if q["kind"] == "explain_txn" and isinstance(q["choices"], dict) and type(q["choices"].get("bank_txn_id")) is int:
            try:
                q["debit"] = repo.debit(conn, user.business_id, q["choices"]["bank_txn_id"])
            except repo.NotFound:
                continue
            q["bills"] = repo.bills_a_debit_could_pay(conn, user.business_id, q["debit"]["amount_paise"])
    return render(request, "attention.html", {
        "questions": questions,
        "candidates": candidates, "shown": shown,
        "accounts": [a for a in all_accounts if a["drift_status"] != "OK"],
        "all_accounts": all_accounts,
        "overrides": repo.active_overrides(conn, user.business_id),
        "options": repo.options(conn, user.business_id, run["id"], today=request.app.state.clock.today())
        if run else [],
        "message": message, "errors": errors or {}, "values": values or {},
    }, status=status)


def prefill(c: dict, accounts: list[dict]) -> dict[str, str]:
    """The confirm form's starting values: a typed entry's record, or what was
    read from a bank email (amount as written, account by its last digits)."""
    if c["record_type"] == "txn":
        x = c["extract"]
        last4 = str(x.get("account_last4") or "")
        match = [a["id"] for a in accounts if last4 and a["account_mask"].endswith(last4)]
        return {"account_id": str(match[0]) if match else "", "direction": x.get("direction") or "",
                "amount": x.get("amount_text") or "", "txn_date": x.get("txn_date") or "",
                "counterparty": x.get("counterparty") or "", "reference": x.get("reference") or ""}
    r = c["record"]
    out = {k: "" if r.get(k) is None else str(r[k]) for k in
           ("party", "invoice_number", "invoice_date", "due_date", "priority", "expected_date", "confidence")}
    out["amount"] = format_inr(r["amount_paise"]) if type(r.get("amount_paise")) is int else ""
    return out


@router.get("/attention")
def attention(request: Request, user: User = Depends(owner_only), conn: sqlite3.Connection = Depends(db)):
    return attention_page(request, conn, user)


@router.post("/candidates/{candidate_id}/confirm")
async def confirm(candidate_id: int, request: Request, user: User = Depends(owner_only),
                  conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    try:
        actions.confirm_candidate(conn, user, candidate_id, values, clock=request.app.state.clock)
    except actions.FieldErrors as e:
        return attention_page(request, conn, user, errors={candidate_id: e.errors},
                              values={candidate_id: e.values}, status=422)
    return done(request, "/attention")


@router.post("/candidates/{candidate_id}/reject")
async def reject(candidate_id: int, request: Request, user: User = Depends(owner_only),
                 conn: sqlite3.Connection = Depends(db)):
    actions.reject_candidate(conn, user, candidate_id, clock=request.app.state.clock)
    return done(request, "/attention")


@router.post("/options/{option_id}/choose")
async def choose(option_id: int, request: Request, user: User = Depends(owner_only),
                 conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    if values.get("undo"):  # take back an authorisation or a delay in force (CHG-021)
        actions.undo_option(conn, user, option_id, clock=request.app.state.clock)
        return done(request, "/attention")
    try:
        actions.choose_option(conn, user, option_id, clock=request.app.state.clock)
    except actions.Stale as e:
        return stale_page(request, conn, user, str(e))
    return done(request, "/")


@router.post("/questions/{question_id}/answer")
async def answer(question_id: int, request: Request, user: User = Depends(owner_only),
                 conn: sqlite3.Connection = Depends(db)):
    """confirm_record hands off to the candidate's confirm or reject through
    choices_json; confirm_balance to the account's confirm-balance. Agent
    questions wait for the agent loop (CHG-008)."""
    q = repo.question(conn, user.business_id, question_id)
    if q["status"] != "OPEN":
        raise actions.Refused("This question is already answered.")
    values = await form_values(request)
    clock = request.app.state.clock
    try:
        choices = json.loads(q["choices_json"]) if q["choices_json"] else {}
    except ValueError:
        choices = None
    if not isinstance(choices, dict):
        raise actions.Refused("This question's choices can't be read.")
    if q["kind"] == "confirm_record":
        cid = choices.get("candidate_id")
        if type(cid) is not int:
            raise actions.Refused("This question has no entry to confirm.")
        repo.candidate(conn, user.business_id, cid)  # 404 outside the business
        if values.get("decision") == "reject":
            actions.reject_candidate(conn, user, cid, clock=clock)
            return done(request, "/attention")
        try:
            actions.confirm_candidate(conn, user, cid, values, clock=clock)
        except actions.FieldErrors as e:
            return attention_page(request, conn, user, errors={cid: e.errors}, values={cid: e.values}, status=422)
        return done(request, "/attention")
    if q["kind"] == "confirm_balance":
        account_id = choices.get("account_id")
        if type(account_id) is not int:
            accounts = [a for a in repo.accounts_not_ok(conn, user.business_id) if a["drift_status"] == "ASK_OWNER"]
            if len(accounts) != 1:
                raise actions.Refused("Confirm the balance on the Accounts page.")
            account_id = accounts[0]["id"]
        actions.confirm_balance(conn, user, account_id, str(values.get("amount", "")), clock=clock)
        return done(request, "/attention")
    if q["kind"] == "explain_txn":
        try:
            actions.explain_debit(conn, user, q, values, clock=clock)
        except actions.FieldErrors as e:
            return attention_page(request, conn, user, message=" ".join(e.errors.values()), status=422)
        return done(request, "/attention")
    raise actions.Refused("Answers to this kind of question come with the agent (a later change).")
