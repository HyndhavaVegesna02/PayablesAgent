"""Reconciliation and drift (TDD Part 2, "Reconciliation and drift"; batch 2
plan, CHG-005). Matching is plain code with exact amounts in paise; every
state change goes through ledger.writer as actor `reconciler`. The cases this
code cannot settle are opened for the exception agent (CHG-008).

These functions write the ledger and the case, and return what the caller
(app/jobs/reconcile.py) must queue next: a replan, the agent's run_case, or a
23:00 drift recheck. Callers run them inside one transaction with that
queueing, so a match and its replan request land together or not at all."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from app.clock import TIMEZONE, Clock
from app.domain.money import format_inr
from app.ledger import writer
from app.ledger.writer import EntityRef

RECONCILER = "reconciler"
RECHECK_AT = (23, 0)  # drift check step 3: an alert's mismatch is checked again at 23:00
_ONE_EVENT_SUBJECTS = ("bank_txn:", "candidate:")
_NOISE_WORDS = frozenset({"PVT", "PRIVATE", "LTD", "LIMITED", "MS"})  # and M/S, removed first


@dataclass
class Result:
    """What happened, and what the caller should queue."""

    outcome: str
    replan: bool = False
    case_ids: list[int] = field(default_factory=list)
    recheck_at: datetime | None = None  # queue a drift recheck at this time


# --- names --------------------------------------------------------------------------


def normalise_name(name: str | None) -> str:
    """Upper case, punctuation removed, and PVT, LTD, M/S and the like dropped."""
    if not name:
        return ""
    text = re.sub(r"\bM\s*/\s*S\b", " ", name.upper())
    words = re.sub(r"[^A-Z0-9]+", " ", text).split()
    return " ".join(w for w in words if w not in _NOISE_WORDS)


def name_matches(counterparty: str | None, names: list[str]) -> bool:
    """A name matches when it equals, or contains, the vendor's name or an alias."""
    seen = normalise_name(counterparty)
    if not seen:
        return False
    for n in names:
        want = normalise_name(n)
        if want and (seen == want or f" {want} " in f" {seen} "):
            return True
    return False


def party_names(conn: sqlite3.Connection, party_id: int | None) -> list[str]:
    if party_id is None:
        return []
    row = conn.execute("SELECT name, aliases_json FROM party WHERE id = ?", (party_id,)).fetchone()
    if row is None:
        return []
    try:
        aliases = json.loads(row["aliases_json"])
    except json.JSONDecodeError:
        aliases = []  # a malformed alias list never blocks matching on the name itself
    return [row["name"], *(a for a in aliases if isinstance(a, str))]


# --- cases --------------------------------------------------------------------------


CaseKind = Literal["unknown_txn", "drift", "failed_payment", "ambiguous_match"]


def case_file(goal: str, facts: list[str], unknowns: list[str]) -> str:
    """The five-part case file (TDD Part 2, "The case file"). Code fills in the
    facts when the case opens; findings and notes are the agent's (CHG-008)."""
    lines = ["## Goal", goal, "", "## Facts"]
    lines += [f"- {f}" for f in facts]
    lines += ["", "## Findings", "(none yet)", "", "## Unknowns"]
    lines += [f"- {u}" for u in unknowns]
    lines += ["", "## Notes", "(none yet)", ""]
    return "\n".join(lines)


def open_case(
    conn: sqlite3.Connection,
    business_id: int,
    kind: CaseKind,
    subject_ref: str,
    stake_paise: int,
    *,
    goal: str,
    facts: list[str],
    unknowns: list[str],
    clock: Clock,
) -> int:
    """Opens an exception case. It starts at high thinking when the stake is
    above the owner's escalation amount, otherwise at medium.

    A subject that is one event (a bank_txn or a candidate) gets one case, so a
    job that runs twice (a crash before mark_done) opens one. An account is not
    one event: each drift episode gets its own case, and check_drift resolves
    the old one when the gap closes."""
    if subject_ref.startswith(_ONE_EVENT_SUBJECTS):
        open_already = conn.execute(
            "SELECT id FROM agent_case WHERE business_id = ? AND kind = ? AND subject_ref = ? AND status = 'OPEN'",
            (business_id, kind, subject_ref),
        ).fetchone()
        if open_already is not None:
            return open_already[0]
    threshold = conn.execute(
        "SELECT escalation_stake_paise FROM business WHERE id = ?", (business_id,)
    ).fetchone()[0]
    now = clock.now().isoformat()
    cur = conn.execute(
        "INSERT INTO agent_case (business_id, kind, subject_ref, stake_paise, thinking, case_file_md, "
        "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)",
        (business_id, kind, subject_ref, stake_paise, "high" if stake_paise > threshold else "medium",
         case_file(goal, facts, unknowns), now, now),
    )
    return cur.lastrowid


def ask_about_debit(conn: sqlite3.Connection, t: dict[str, Any], case_id: int) -> int:
    """Asks the owner what a debit the reconciler could not match was for
    (batch 4 plan, CHG-022, Q1): an explain_txn question linked to its case,
    answered on Needs attention. One question per case, so a job that runs
    twice asks once. The text is built by code from the alert's fields."""
    existing = conn.execute(
        "SELECT id FROM owner_question WHERE business_id = ? AND kind = 'explain_txn' "
        "AND json_extract(choices_json, '$.case_id') = ?", (t["business_id"], case_id),
    ).fetchone()
    if existing is not None:
        return existing[0]
    payee = t["counterparty"] or "an unnamed payee"
    body = (f"A {format_inr(t['amount_paise'])} debit on {t['txn_date']} to {payee}"
            f"{' (reference ' + t['reference'] + ')' if t['reference'] else ''} was not matched to a bill. "
            "Which bill did it pay, if any?")
    return conn.execute(
        "INSERT INTO owner_question (business_id, case_id, kind, body_text, choices_json, status) "
        "VALUES (?, ?, 'explain_txn', ?, ?, 'OPEN')",
        (t["business_id"], case_id, body, json.dumps({"case_id": case_id, "bank_txn_id": t["id"]})),
    ).lastrowid


# --- matching -----------------------------------------------------------------------


def _txn(conn: sqlite3.Connection, txn_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT t.*, a.business_id, a.account_mask FROM bank_txn t JOIN bank_account a ON a.id = t.account_id "
        "WHERE t.id = ?", (txn_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"bank_txn {txn_id} does not exist")
    return dict(row)


def _within(d: str | None, around: date, window_days: int) -> bool:
    return d is not None and abs((date.fromisoformat(d) - around).days) <= window_days


def _txn_facts(t: dict[str, Any]) -> list[str]:
    return [
        f"{t['direction'].capitalize()} of {format_inr(t['amount_paise'])} on {t['txn_date']} "
        f"in account {t['account_mask']} (bank_txn:{t['id']})",
        f"Counterparty as written: {t['counterparty'] or '(none)'}; reference: {t['reference'] or '(none)'}",
    ]


def match_debit(conn: sqlite3.Connection, txn_id: int, *, window_days: int, clock: Clock,
                trace_run_id: str | None = None) -> Result:
    """A new debit (TDD steps 1-5)."""
    t = _txn(conn, txn_id)
    if t["status"] != "UNMATCHED" or t["direction"] != "debit":
        return Result(f"bank_txn {txn_id} is a {t['status']} {t['direction']}: nothing to match")
    txn_day = date.fromisoformat(t["txn_date"])
    cands = [
        dict(r) for r in conn.execute(
            # D12: a bill the owner already marked PAID, whose debit has not been
            # linked yet, is a candidate on the same terms as an approved one.
            "SELECT * FROM payable WHERE business_id = ? AND amount_paise = ? "
            "AND (status = 'PAYMENT_EXPECTED' OR (status = 'PAID' AND matched_txn_id IS NULL)) "
            "ORDER BY id", (t["business_id"], t["amount_paise"]),
        )
        if _within(r["planned_date"], txn_day, window_days)
    ]
    named = [c for c in cands if name_matches(t["counterparty"], party_names(conn, c["party_id"]))]
    kw = dict(conn=conn, clock=clock, trace_run_id=trace_run_id)
    ref = f"bank_txn:{txn_id}"

    if len(named) == 1:
        bill = named[0]
        why = (f"Debit of {format_inr(t['amount_paise'])} on {t['txn_date']} to "
               f"{t['counterparty']} matches bill {bill['id']} planned for {bill['planned_date']}.")
        writer.transition(EntityRef("bank_txn", txn_id), "MATCHED", RECONCILER, why, f"payable:{bill['id']}",
                          fields={"party_id": bill["party_id"]}, **kw)
        if bill["status"] == "PAID":
            writer.link_payment(bill["id"], txn_id, RECONCILER, why + " The owner had already marked it paid.",
                                ref, **kw)
            return Result(f"linked to bill {bill['id']}, already PAID", replan=True)
        writer.transition(EntityRef("payable", bill["id"]), "PAID", RECONCILER, why, ref,
                          fields={"matched_txn_id": txn_id}, **kw)
        return Result(f"matched bill {bill['id']}: PAID", replan=True)

    if cands:
        review = named or cands
        why = ("several bills match this debit" if len(review) > 1
               else "a bill has this amount and date but not this payee's name")
        for bill in review:
            if bill["status"] == "PAID":
                continue  # already paid by the owner: it stays PAID and is listed in the case
            writer.transition(EntityRef("payable", bill["id"]), "REVIEW", RECONCILER,
                              f"Debit {ref} is ambiguous: {why}.", ref, **kw)
        case = open_case(
            conn, t["business_id"], "ambiguous_match", ref, t["amount_paise"],
            goal=f"Decide which bill, if any, debit {ref} paid.",
            facts=_txn_facts(t) + [
                f"Candidate bill {b['id']} ({b['status']}): {format_inr(b['amount_paise'])}, "
                f"planned {b['planned_date']}, payee names {party_names(conn, b['party_id'])}" for b in review
            ],
            unknowns=["Which bill this debit paid"], clock=clock,
        )
        ask_about_debit(conn, t, case)
        return Result(f"ambiguous ({why}): bills {[b['id'] for b in review]} to REVIEW", replan=True,
                      case_ids=[case])

    case = open_case(
        conn, t["business_id"], "unknown_txn", ref, t["amount_paise"],
        goal=f"Find out what debit {ref} was.", facts=_txn_facts(t) + ["No approved payment matches it"],
        unknowns=["What this payment was for"], clock=clock,
    )
    ask_about_debit(conn, t, case)
    # The debit already lowers the balance the next plan starts from.
    return Result("no bill matches: debit stays UNMATCHED", replan=True, case_ids=[case])


def _asked_dates(conn: sqlite3.Connection, business_id: int) -> dict[int, list[str]]:
    """Dates the owner asked a customer to pay by: the chosen early_receipt
    options (batch 3 plan, D13). Choosing one changes no ledger row (Q1), so
    the receivable keeps its expected date; a credit near the asked date is
    that receivable paying early, and it matches on the same name and amount
    rules as one near the expected date."""
    asked: dict[int, list[str]] = {}
    for rid, day in conn.execute(
        "SELECT json_extract(o.params_json, '$.receivable_id'), json_extract(o.params_json, '$.to_date') "
        "FROM shortfall_option o JOIN plan_run r ON r.id = o.plan_run_id "
        "WHERE r.business_id = ? AND o.kind = 'early_receipt' AND o.chosen_at IS NOT NULL",
        (business_id,),
    ).fetchall():
        if isinstance(rid, int) and isinstance(day, str):
            asked.setdefault(rid, []).append(day)
    return asked


def match_credit(conn: sqlite3.Connection, txn_id: int, *, window_days: int, clock: Clock,
                 trace_run_id: str | None = None) -> Result:
    """A new credit: the same steps against open receivables. A receivable has
    no REVIEW state, so anything but one clean match is a case."""
    t = _txn(conn, txn_id)
    if t["status"] != "UNMATCHED" or t["direction"] != "credit":
        return Result(f"bank_txn {txn_id} is a {t['status']} {t['direction']}: nothing to match")
    txn_day = date.fromisoformat(t["txn_date"])
    open_rx = [dict(r) for r in conn.execute(
        "SELECT * FROM receivable WHERE business_id = ? AND confidence IN ('COMMITTED', 'EXPECTED', 'UNKNOWN') "
        "ORDER BY id", (t["business_id"],),
    )]
    named = [r for r in open_rx if name_matches(t["counterparty"], party_names(conn, r["party_id"]))]
    asked = _asked_dates(conn, t["business_id"])
    exact = [r for r in named if r["amount_paise"] == t["amount_paise"]
             and (r["expected_date"] is None or _within(r["expected_date"], txn_day, window_days)
                  or any(_within(d, txn_day, window_days) for d in asked.get(r["id"], ())))]
    ref = f"bank_txn:{txn_id}"
    kw = dict(conn=conn, clock=clock, trace_run_id=trace_run_id)

    if len(exact) == 1:
        rx = exact[0]
        when = (f"expected {rx['expected_date']}" if rx["expected_date"] is None
                or _within(rx["expected_date"], txn_day, window_days)
                else f"asked for by {', '.join(asked[rx['id']])}")
        why = (f"Credit of {format_inr(t['amount_paise'])} on {t['txn_date']} from {t['counterparty']} "
               f"matches receivable {rx['id']} {when}.")
        writer.transition(EntityRef("bank_txn", txn_id), "MATCHED", RECONCILER, why, f"receivable:{rx['id']}",
                          fields={"party_id": rx["party_id"]}, **kw)
        writer.transition(EntityRef("receivable", rx["id"]), "CONFIRMED", RECONCILER, why, ref,
                          fields={"matched_txn_id": txn_id}, **kw)
        return Result(f"matched receivable {rx['id']}: CONFIRMED", replan=True)

    if named:
        why = ("several receivables match" if len(exact) > 1
               else "the payer matches a receivable but the amount or date does not")
        case = open_case(
            conn, t["business_id"], "ambiguous_match", ref, t["amount_paise"],
            goal=f"Decide which receivable, if any, credit {ref} settles.",
            facts=_txn_facts(t) + [
                f"Receivable {r['id']} from the same payer: {format_inr(r['amount_paise'])}, "
                f"expected {r['expected_date'] or '(no date)'}" for r in named
            ],
            unknowns=["Whether this is a part payment, an overpayment or another invoice"], clock=clock,
        )
        return Result(f"ambiguous credit ({why})", case_ids=[case])

    case = open_case(
        conn, t["business_id"], "unknown_txn", ref, t["amount_paise"],
        goal=f"Find out what credit {ref} was.", facts=_txn_facts(t) + ["No open receivable matches it"],
        unknowns=["Who paid this and for what"], clock=clock,
    )
    return Result("no receivable matches: credit stays UNMATCHED", case_ids=[case])


# --- failures and reversals -------------------------------------------------------------


def handle_failure(conn: sqlite3.Connection, candidate_id: int, *, window_days: int, clock: Clock,
                   trace_run_id: str | None = None) -> Result:
    """A failure or return email, matched to a PAID bill by amount and its
    debit's reference, or to a PAYMENT_EXPECTED bill by amount and date. The
    bill is REOPENED and any original debit REVERSED; a replan follows."""
    cand = conn.execute(
        "SELECT c.*, d.business_id FROM candidate c JOIN source_document d ON d.id = c.source_document_id "
        "WHERE c.id = ?", (candidate_id,)
    ).fetchone()
    if cand is None:
        raise LookupError(f"candidate {candidate_id} does not exist")
    rec = json.loads(cand["payload_json"])["record"]
    business_id, amount, reference = cand["business_id"], rec["amount_paise"], rec["original_reference"]
    failed_on = date.fromisoformat(rec["failure_date"])
    source_ref = f"candidate:{candidate_id}"
    kw = dict(conn=conn, clock=clock, trace_run_id=trace_run_id)

    paid = [] if reference is None else [dict(r) for r in conn.execute(
        "SELECT p.*, t.id AS txn_id FROM payable p JOIN bank_txn t ON t.id = p.matched_txn_id "
        "WHERE p.business_id = ? AND p.status = 'PAID' AND t.amount_paise = ? AND t.reference = ? "
        # UNMATCHED too: the owner marked a REVIEW bill paid, which links its debit
        # without the reconciler matching it (D12).
        "AND t.status IN ('MATCHED', 'UNMATCHED') ORDER BY p.id", (business_id, amount, reference),
    )]
    expected = [dict(r) for r in conn.execute(
        "SELECT * FROM payable WHERE business_id = ? AND status = 'PAYMENT_EXPECTED' AND amount_paise = ? "
        "ORDER BY id", (business_id, amount),
    ) if _within(r["planned_date"], failed_on, window_days)]
    bills = paid + expected
    why = (f"Payment of {format_inr(amount)} failed or was returned on {rec['failure_date']} "
           f"({rec['reason']}).")

    if len(bills) == 1:
        bill = bills[0]
        if bill.get("txn_id") is not None:
            writer.transition(EntityRef("bank_txn", bill["txn_id"]), "REVERSED", RECONCILER, why, source_ref, **kw)
        writer.transition(EntityRef("payable", bill["id"]), "REOPENED", RECONCILER, why, source_ref, **kw)
        return Result(f"bill {bill['id']} REOPENED", replan=True)

    # No single bill. A debit for this payment that was never matched is still
    # reversed, so the balance stops counting money that came back.
    replan = False
    if reference is not None:
        for (txn_id,) in conn.execute(
            "SELECT t.id FROM bank_txn t JOIN bank_account a ON a.id = t.account_id WHERE a.business_id = ? "
            "AND t.status = 'UNMATCHED' AND t.direction = 'debit' AND t.amount_paise = ? AND t.reference = ? "
            # A debit a bill holds (the owner's REVIEW -> PAID link) is left for the
            # case, like a MATCHED one: reversing it would leave that PAID bill
            # pointing at money that came back, and the plan would overstate cash.
            "AND NOT EXISTS (SELECT 1 FROM payable p WHERE p.matched_txn_id = t.id)",
            (business_id, amount, reference),
        ).fetchall():
            writer.transition(EntityRef("bank_txn", txn_id), "REVERSED", RECONCILER, why, source_ref, **kw)
            replan = True
    case = open_case(
        conn, business_id, "failed_payment", source_ref, amount,
        goal="Find the payment this failure or return email is about.",
        facts=[why, f"Original reference: {reference or '(none given)'}",
               f"Bills that could match: {[b['id'] for b in bills] or 'none'}"],
        unknowns=["Which bill's payment failed"], clock=clock,
    )
    return Result(f"failure matches {len(bills)} bills: failed_payment case", replan=replan, case_ids=[case])


# --- drift ----------------------------------------------------------------------------


def resolve_drift_cases(conn: sqlite3.Connection, account_id: int, *, clock: Clock) -> list[int]:
    """The gap closed by itself (a found transaction): the account's open
    drift cases are RESOLVED, with a note in the case file."""
    now = clock.now().isoformat()
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM agent_case WHERE kind = 'drift' AND subject_ref = ? AND status = 'OPEN'",
        (f"bank_account:{account_id}",),
    )]
    for case_id in ids:
        conn.execute(
            "UPDATE agent_case SET status = 'RESOLVED', updated_at = ?, "
            "case_file_md = case_file_md || ? WHERE id = ?",
            (now, f"- {now}: the gap closed: the calculated balance equals the reported one (reconciler).\n",
             case_id),
        )
    return ids


def _recheck_time(reported_at: datetime) -> datetime:
    local = reported_at.astimezone(TIMEZONE)
    at = local.replace(hour=RECHECK_AT[0], minute=RECHECK_AT[1], second=0, microsecond=0)
    return at if at > local else at + timedelta(days=1)


def check_drift(
    conn: sqlite3.Connection,
    account_id: int,
    *,
    source: Literal["alert", "statement", "recheck", "new_txn"],
    clock: Clock,
    reported_paise: int | None = None,
    reported_at: datetime | None = None,
    trace_run_id: str | None = None,
) -> Result:
    """Drift check (TDD steps 1-5, code side). `alert` and `statement` bring a
    new reported balance; `recheck` (23:00) and `new_txn` (a transaction
    written while CHECKING) compare against the one already stored."""
    kw = dict(conn=conn, clock=clock, trace_run_id=trace_run_id)
    if source in ("alert", "statement"):
        if reported_paise is None or reported_at is None:
            raise ValueError(f"a {source} drift check needs the reported balance and its time")
        calc = writer.calculated_balance(conn, account_id, reported_at.astimezone(TIMEZONE).date())
        writer.record_reported_balance(
            account_id, reported_paise, reported_at.isoformat(), RECONCILER,
            f"Balance reported by {source}: {format_inr(reported_paise)}; calculated {format_inr(calc)}.",
            f"{source}", reconciled=calc == reported_paise, **kw,
        )
    acct = conn.execute("SELECT * FROM bank_account WHERE id = ?", (account_id,)).fetchone()
    if acct["reported_balance_paise"] is None:
        return Result("no reported balance to compare")
    reported, at = acct["reported_balance_paise"], datetime.fromisoformat(acct["reported_at"])
    calc = writer.calculated_balance(conn, account_id, at.astimezone(TIMEZONE).date())
    gap = reported - calc
    status = acct["drift_status"]

    if gap == 0:
        if status == "CHECKING":
            writer.set_drift_status(account_id, "OK", RECONCILER,
                                    f"The gap closed: calculated {format_inr(calc)} equals the reported balance.",
                                    f"bank_account:{account_id}", **kw)
            resolved = resolve_drift_cases(conn, account_id, clock=clock)
            return Result(f"gap closed: CHECKING -> OK; drift cases {resolved} resolved", replan=True)
        return Result("balances agree")

    if status != "OK":
        return Result(f"still {status}: gap {format_inr(gap)}")
    if source == "alert":
        return Result(f"gap {format_inr(gap)}: recheck at 23:00", recheck_at=_recheck_time(at))

    writer.set_drift_status(
        account_id, "CHECKING", RECONCILER,
        f"Reported {format_inr(reported)} on {at.date()} but calculated {format_inr(calc)}: "
        f"a gap of {format_inr(gap)}.", f"bank_account:{account_id}", **kw,
    )
    case = open_case(
        conn, acct["business_id"], "drift", f"bank_account:{account_id}", abs(gap),
        goal=f"Explain the {format_inr(abs(gap))} gap in account {acct['account_mask']}.",
        facts=[f"Bank-reported balance: {format_inr(reported)} at {acct['reported_at']}",
               f"Calculated balance for that day: {format_inr(calc)}",
               f"Gap (reported minus calculated): {format_inr(gap)}",
               f"Found by: {source}"],
        unknowns=["Which transactions are missing from the ledger"], clock=clock,
    )
    return Result(f"gap {format_inr(gap)}: CHECKING, drift case {case}", replan=True, case_ids=[case])
