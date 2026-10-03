"""The exception agent's scenarios (batch 6, CHG-008, S7), end to end through
the real worker, with the scripted fixture AI (fixtures/ai_replies.json,
agent_scripts) answering every AgentStep from the case file alone, as Gemini
would. The owner acts through the web app.

1. An unknown debit is explained by an invoice email; the bill goes to the
   owner to confirm, and its new bank details still raise a bank change.
2. An unknown debit nothing explains reaches the owner, whose answer settles it.
3. A ₹20,000 drift is recovered from an alert the poll missed (D21).
4. A drift nothing explains ends at the owner's confirm_balance.
5. A hijacking email changes nothing; its text reaches the owner escaped.
6. Escalation: medium -> high -> owner, both rules in the trace."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from app.agent import cases, escalation
from app.ai.fixture_backend import FixtureBackend
from app.clock import TIMEZONE
from app.domain.models import BankTxnNew
from app.jobs import queue
from app.ledger import writer
from app.web import actions, repo
from app.web.auth import User
from app.web.routes.attention import prefill
from app.worker import default_handlers
from tests.web_helpers import login, make_web_env, post
from tests.worker_helpers import deliver, run_all

SHORT = "04-debit-city-electricity-balance-short.eml"
MISSED = "11-debit-shree-transport-missed.eml"
INVOICE = "09-invoice-ashirwad-new-bank.eml"
OWNER = User(id=1, business_id=1, email="owner@example.test", role="owner")


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    env.handlers = default_handlers(FixtureBackend())
    yield env, client
    env.conn.close()


def at(env, day, hour, minute=0):
    env.clock.advance(datetime(2026, 10, day, hour, minute, tzinfo=TIMEZONE) - env.clock.now())


def enqueue(env, kind, payload=None):
    queue.enqueue(env.conn, kind=kind, payload=payload or {}, clock=env.clock)
    env.conn.commit()


def debit(env, rupees, counterparty, day=14):
    """A debit in the ledger (as a statement or alert would put it) and its reconcile job."""
    txn = writer.create_bank_txn(
        BankTxnNew(account_id=1, direction="debit", amount_paise=rupees * 100, txn_date=date(2026, 10, day),
                   counterparty=counterparty, dedup_key=f"test:{counterparty}", status="UNMATCHED"),
        actor="pipeline", reason="test debit", source_ref=f"test:{counterparty}", conn=env.conn, clock=env.clock)
    enqueue(env, "reconcile_txn", {"bank_txn_id": txn.id})
    return txn.id


def case_of(env, kind, subject_ref=None):
    sql, args = "SELECT id FROM agent_case WHERE kind = ?", [kind]
    if subject_ref:
        sql, args = sql + " AND subject_ref = ?", args + [subject_ref]
    (row,) = env.conn.execute(sql, args).fetchall()
    return cases.load(env.conn, row[0])


def questions(env, case_id, kind):
    """The case's questions of one kind (the reconciler also asks explain_txn about a debit)."""
    return env.conn.execute("SELECT id, kind, body_text, choices_json, status FROM owner_question "
                            "WHERE case_id = ? AND kind = ? ORDER BY id", (case_id, kind)).fetchall()


def dead_jobs(env):
    return env.conn.execute("SELECT kind, last_error FROM job WHERE status IN ('dead', 'failed')").fetchall()


def test_1_an_unknown_debit_is_explained_by_an_invoice_email(web):
    env, client = web
    env.conn.execute("UPDATE party SET bank_account_mask = 'XXXX4410', bank_ifsc = 'SBIN0001234', "
                     "bank_status = 'verified' WHERE id = 1")  # Ashirwad's details on record
    at(env, 14, 12)
    deliver(env, INVOICE)
    txn = debit(env, 47_200, "APS PAPERS")
    run_all(env, env.handlers)
    case = case_of(env, "unknown_txn", f"bank_txn:{txn}")
    assert case.status == "RESOLVED" and "invoice AP/2610/140" in case.state["summary"]
    assert [f["source"].split("(")[0] for f in case.state["findings"]] == ["search_gmail", "add_candidate"]
    (q,) = questions(env, case.id, "confirm_record")
    assert q["status"] == "OPEN"
    cid = json.loads(q["choices_json"])["candidate_id"]
    assert env.conn.execute("SELECT COUNT(*) FROM payable WHERE invoice_number = 'AP/2610/140'").fetchone()[0] == 0
    # the owner confirms the bill; its new bank details still raise a bank change (defence in depth)
    c = next(c for c in repo.waiting_candidates(env.conn, 1) if c["id"] == cid)  # on the owner's page
    actions.confirm_candidate(env.conn, OWNER, cid, prefill(c, repo.accounts(env.conn, 1)), clock=env.clock)
    env.conn.commit()
    party = env.conn.execute("SELECT bank_account_mask, bank_status FROM party WHERE id = 1").fetchone()
    assert tuple(party) == ("XXXX4410", "change_pending")
    assert env.conn.execute("SELECT COUNT(*) FROM owner_question WHERE kind = 'approve_bank_change' "
                            "AND status = 'OPEN'").fetchone()[0] == 1
    assert dead_jobs(env) == []


def test_2_an_unknown_debit_nothing_explains_reaches_the_owner(web):
    env, client = web
    at(env, 14, 12)
    txn = debit(env, 12_500, "RAMESH K")
    run_all(env, env.handlers)
    case = case_of(env, "unknown_txn", f"bank_txn:{txn}")
    assert case.status == "ASK_OWNER"
    (q,) = questions(env, case.id, "agent_question")
    assert json.loads(q["choices_json"])["choices"] == ["An advance to a worker", "I don't know it"]
    csrf = login(client)
    page = client.get("/attention").text
    assert "matches no bill and no email" in page and 'value="An advance to a worker"' in page
    assert post(client, f"/questions/{q['id']}/answer", csrf, {"choice": "An advance to a worker"}).status_code == 303
    run_all(env, env.handlers)
    case = cases.load(env.conn, case.id)
    assert case.status == "RESOLVED" and "The answer: An advance to a worker" in case.case_file_md
    assert "The owner explained the ₹12,500" in client.get("/attention").text  # What the assistant found


def _drift(env, *, missed_alert):
    at(env, 15, 9)
    enqueue(env, "poll_mail")  # an empty poll on Thu morning: later polls look back to Wed
    run_all(env, env.handlers)
    at(env, 15, 13)
    deliver(env, SHORT, *([MISSED] if missed_alert else []))
    enqueue(env, "poll_mail")
    run_all(env, env.handlers)
    assert env.conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0] == 1  # 11 is not polled
    at(env, 15, 23)
    run_all(env, env.handlers)
    return case_of(env, "drift")


def test_3_a_drift_is_recovered_from_an_alert_the_poll_missed(web):
    env, _ = web
    drift = _drift(env, missed_alert=True)
    assert drift.status == "RESOLVED" and "SHREE TRANSPORT" in drift.state["summary"]
    acct = env.conn.execute("SELECT drift_status, reported_balance_paise FROM bank_account WHERE id = 1").fetchone()
    assert tuple(acct) == ("OK", 56_500_000)
    txn = env.conn.execute("SELECT id, amount_paise, txn_date FROM bank_txn WHERE counterparty = 'SHREE TRANSPORT'"
                           ).fetchone()
    assert tuple(txn[1:]) == (2_000_000, "2026-10-13")
    ev = env.conn.execute("SELECT actor, source_ref FROM event WHERE entity = 'bank_txn' AND entity_id = ? "
                          "AND event_type = 'BANK_TXN_CREATED'", (txn[0],)).fetchone()
    assert tuple(ev) == ("pipeline", f"agent:case:{drift.id} via gmail:{MISSED}")  # D21
    ok = env.conn.execute("SELECT actor FROM event WHERE entity = 'bank_account' AND event_type = 'BANK_ACCOUNT_OK'"
                          ).fetchone()
    assert ok[0] == "reconciler"
    plan = env.conn.execute("SELECT opening_cash_paise FROM plan_run WHERE is_current = 1").fetchone()
    assert plan[0] == 56_500_000
    assert dead_jobs(env) == []


def test_4_a_drift_nothing_explains_ends_at_the_owners_confirm_balance(web):
    env, client = web
    drift = _drift(env, missed_alert=False)
    assert (drift.status, drift.thinking, drift.escalation_rule) == ("ASK_OWNER", "high", escalation.MAX_STEPS)
    assert drift.state["steps_total"] == 12
    assert env.conn.execute("SELECT drift_status FROM bank_account WHERE id = 1").fetchone()[0] == "ASK_OWNER"
    (q,) = questions(env, drift.id, "confirm_balance")
    assert json.loads(q["choices_json"]) == {"account_id": 1, "case_id": drift.id}
    csrf = login(client)
    assert post(client, f"/questions/{q['id']}/answer", csrf, {"amount": "5,65,000"}).status_code == 303
    assert env.conn.execute("SELECT drift_status FROM bank_account WHERE id = 1").fetchone()[0] == "OK"
    assert cases.load(env.conn, drift.id).status == "CLOSED_BY_OWNER"
    adj = env.conn.execute("SELECT direction, amount_paise FROM bank_txn WHERE status = 'ADJUSTMENT'").fetchone()
    assert tuple(adj) == ("debit", 2_000_000)


def test_5_a_hijacking_email_changes_nothing_and_reaches_the_owner_escaped(web):
    env, client = web
    at(env, 14, 12)
    deliver(env, INVOICE)
    terms = "SELECT id, amount_paise, due_date, priority, approved_at FROM payable ORDER BY id"
    payables = [tuple(r) for r in env.conn.execute(terms)]
    parties = [tuple(r) for r in env.conn.execute("SELECT * FROM party ORDER BY id")]
    (last_event,) = env.conn.execute("SELECT MAX(id) FROM event").fetchone()
    txn = debit(env, 15_000, "ASHIRWAD PAPER")
    run_all(env, env.handlers)
    case = case_of(env, "unknown_txn", f"bank_txn:{txn}")
    assert any("refused unknown tool 'approve_bank_change'" in n for n in case.state["notes"])
    assert case.status == "ASK_OWNER"
    assert [tuple(r) for r in env.conn.execute(terms)] == payables
    assert [tuple(r) for r in env.conn.execute("SELECT * FROM party ORDER BY id")] == parties
    for table in ("plan_override", "candidate"):
        assert env.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    # the debit's replan plans bills (PLANNED, by the planner); nothing else touched a bill or a party
    actors = {r[0] for r in env.conn.execute("SELECT actor FROM event WHERE entity IN ('payable', 'party') "
                                             "AND id > ?", (last_event,))}
    assert actors <= {"planner"}
    assert env.conn.execute("SELECT COUNT(*) FROM payable WHERE status NOT IN ('CONFIRMED', 'PLANNED')"
                            ).fetchone()[0] == 0
    login(client)
    page = client.get("/attention").text
    assert "&lt;b&gt;50100 2233 9921&lt;/b&gt;" in page and "<b>50100" not in page


def test_6_escalation_runs_medium_then_high_then_asks_the_owner(web):
    env, _ = web
    _drift(env, missed_alert=True)
    txn = env.conn.execute("SELECT id FROM bank_txn WHERE counterparty = 'SHREE TRANSPORT'").fetchone()[0]
    case = case_of(env, "unknown_txn", f"bank_txn:{txn}")
    assert (case.status, case.thinking) == ("ASK_OWNER", "high")
    notes = "\n".join(case.state["notes"])
    assert "the medium run ended (max_validation_failures); rerunning at high thinking" in notes
    assert "the high run ended (max_steps); the owner is asked" in notes
    assert case.state["steps_total"] == 2 + 1 + 6  # a search, two failed candidates; then six at high
    (q,) = questions(env, case.id, "agent_question")
    assert q["body_text"].startswith("The assistant could not settle this case")
    rules = [s["escalation_rule"] for f in Path(env.settings.trace_dir).rglob("*.jsonl")
             for s in map(json.loads, f.read_text(encoding="utf-8").splitlines())
             if s.get("tool") == "escalation" and s.get("input_ref") == f"agent_case:{case.id}"
             and s.get("escalation_rule")]
    assert rules == [escalation.MAX_FAILURES, escalation.MAX_STEPS]


def test_the_fixture_ai_reads_the_step_and_candidates_from_the_case_file_and_passes_unscripted_cases_on():
    from app.ai.fixture_backend import NO_SCRIPT, agent_step, load_agent_scripts

    scripts = load_agent_scripts()
    case_file = ("## Goal\nFind out what debit bank_txn:7 was.\n\n## Facts\n- Debit of ₹20,000 on 2026-10-13\n\n"
                 "## Findings\n- step 1, source search_gmail(query='SHREE TRANSPORT', limit=10):\n"
                 f"    message {MISSED} | ...\n\n## Unknowns\n- x\n\n## Notes\n- step 1: look\n- step 2: propose\n")
    step = agent_step(scripts, case_file)
    assert step["tool"]["args"]["fields"] == {"amount_text": "Rs.3"}  # {step}: the third step
    drift = ("## Goal\nExplain the ₹20,000 gap in account XXXX4821.\n## Findings\n"
             "    candidate 4: VALID, every rule check passed\n    candidate 5: INVALID (x)\n## Notes\n- step 2: a\n")
    assert agent_step(scripts, drift)["final"]["relied_on_candidate_ids"] == [4]
    assert agent_step(scripts, "## Goal\nFind out what credit bank_txn:9 was.\n") == NO_SCRIPT
