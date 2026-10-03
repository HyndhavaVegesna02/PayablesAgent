"""Owner alerts by email (TDD Part 2, "Jobs": send_alert; batch 7, CHG-010b).

Code raises an alert at the TDD's four owner events (a kind and a record
reference, nothing else). The send_alert job sends every unsent alert of a
business as one fixed-template email, to the owner's address in the database,
at most once per `alerts.min_minutes_between_emails`; an alert raised inside
the window waits for the window's end. Every figure is read from the ledger
when the email is built. With no SMTP host configured nothing is sent and the
alerts wait."""

from __future__ import annotations

import functools
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.clock import Clock
from app.jobs import queue
from app.jobs.queue import PermanentJobError
from app.ledger.writer import calculated_balance
from app.notify import templates
from app.notify.smtp import message, send_email

if TYPE_CHECKING:
    from app.worker import Handler, JobContext

KINDS = ("money_received", "payment_failed", "unexpected_debit", "balance_mismatch")


def raise_alert(conn: sqlite3.Connection, business_id: int, kind: str, ref: str, *, clock: Clock) -> None:
    """Records one alert (once per kind and record) and makes sure a send_alert
    job is queued for the business; a queued one absorbs it."""
    if kind not in KINDS:
        raise ValueError(f"not an alert kind: {kind!r}")
    conn.execute("INSERT OR IGNORE INTO owner_alert (business_id, kind, ref, created_at) VALUES (?, ?, ?, ?)",
                 (business_id, kind, ref, clock.now().isoformat()))
    if queue.queued_job_id(conn, "send_alert", business_id) is None:
        queue.enqueue(conn, kind="send_alert", payload={"business_id": business_id}, clock=clock)


def _id(ref: str, prefix: str) -> int:
    if not ref.startswith(prefix + ":"):
        raise ValueError(f"alert ref {ref!r} is not a {prefix}")
    return int(ref.split(":", 1)[1])


def alert_line(conn: sqlite3.Connection, kind: str, ref: str) -> str:
    """The alert's sentence, from the ledger as it is now."""
    if kind == "money_received":
        r = conn.execute("SELECT r.amount_paise, r.business_id, pt.name FROM receivable r "
                         "LEFT JOIN party pt ON pt.id = r.party_id WHERE r.id = ?", (_id(ref, "receivable"),)).fetchone()
        plan = conn.execute("SELECT lowest_balance_paise FROM plan_run WHERE business_id = ? AND is_current = 1",
                            (r["business_id"],)).fetchone()
        return templates.money_received(r["amount_paise"], r["name"], plan[0] if plan else None)
    if kind == "payment_failed":
        if ref.startswith("agent_case:"):
            (stake,) = conn.execute("SELECT stake_paise FROM agent_case WHERE id = ?", (_id(ref, "agent_case"),)).fetchone()
            return templates.payment_failed_unmatched(stake)
        p = conn.execute("SELECT p.amount_paise, pt.name FROM payable p LEFT JOIN party pt ON pt.id = p.party_id "
                         "WHERE p.id = ?", (_id(ref, "payable"),)).fetchone()
        return templates.payment_failed(p["amount_paise"], p["name"])
    if kind == "unexpected_debit":
        t = conn.execute("SELECT t.amount_paise, a.bank_name FROM bank_txn t JOIN bank_account a ON a.id = t.account_id "
                         "WHERE t.id = ?", (_id(ref, "bank_txn"),)).fetchone()
        return templates.unexpected_debit(t["amount_paise"], t["bank_name"])
    if kind == "balance_mismatch":
        account_id = _id(ref, "bank_account")
        a = conn.execute("SELECT bank_name, reported_balance_paise, reported_at FROM bank_account WHERE id = ?",
                         (account_id,)).fetchone()
        on = datetime.fromisoformat(a["reported_at"]).date() if a["reported_at"] else None
        return templates.balance_mismatch(a["bank_name"], a["reported_balance_paise"] or 0,
                                          calculated_balance(conn, account_id, on))
    raise ValueError(f"not an alert kind: {kind!r}")


def send_alerts(conn: sqlite3.Connection, business_id: int, *, settings, app_config, clock: Clock,
                smtp_factory: Callable | None = None) -> str:
    """Sends the business's unsent alerts as one email, or says why not."""
    if not settings.smtp_host:
        return "no SMTP host configured: alerts wait unsent"
    window = timedelta(minutes=app_config.alerts.min_minutes_between_emails)
    (last,) = conn.execute("SELECT MAX(sent_at) FROM owner_alert WHERE business_id = ?", (business_id,)).fetchone()
    if last is not None and clock.now() < datetime.fromisoformat(last) + window:
        at = datetime.fromisoformat(last) + window
        queue.enqueue(conn, kind="send_alert", payload={"business_id": business_id}, run_after=at.isoformat(),
                      idempotency_key=f"send_alert:{business_id}:{at.isoformat()}", clock=clock)
        return f"inside the {window} window: deferred to {at.isoformat()}"
    rows = conn.execute("SELECT id, kind, ref FROM owner_alert WHERE business_id = ? AND sent_at IS NULL ORDER BY id",
                        (business_id,)).fetchall()
    if not rows:
        return "nothing to send"
    owner = conn.execute("SELECT email FROM app_user WHERE business_id = ? AND role = 'owner' ORDER BY id LIMIT 1",
                         (business_id,)).fetchone()
    if owner is None:
        raise PermanentJobError(f"business {business_id} has no owner to alert")
    subject, body = templates.digest([alert_line(conn, r["kind"], r["ref"]) for r in rows],
                                     settings.app_base_url.rstrip("/") + "/attention")
    msg = message(settings.alert_from or settings.smtp_user, owner["email"], subject, body)
    kwargs = {} if smtp_factory is None else {"smtp_factory": smtp_factory}
    send_email(msg, host=settings.smtp_host, port=settings.smtp_port, user=settings.smtp_user,
               password=settings.smtp_password, **kwargs)
    now = clock.now().isoformat()
    conn.executemany("UPDATE owner_alert SET sent_at = ? WHERE id = ?", [(now, r["id"]) for r in rows])
    return f"sent {len(rows)} alert(s) in one email"


def handle_send_alert(ctx: JobContext, *, smtp_factory: Callable | None = None) -> None:
    if set(ctx.payload) != {"business_id"} or type(ctx.payload["business_id"]) is not int:
        raise PermanentJobError(f"send_alert takes only an int business_id, got {sorted(ctx.payload)}")
    try:
        result = send_alerts(ctx.conn, ctx.payload["business_id"], settings=ctx.settings, app_config=ctx.app_config,
                             clock=ctx.clock, smtp_factory=smtp_factory)
    except ValueError as e:  # an address the database should never hold
        raise PermanentJobError(str(e)) from None
    ctx.tracer.step(input_ref=f"business:{ctx.payload['business_id']}", tool="send_alert", result=result)


def handlers(smtp_factory: Callable | None = None) -> dict[str, Handler]:
    return {"send_alert": functools.partial(handle_send_alert, smtp_factory=smtp_factory)}

