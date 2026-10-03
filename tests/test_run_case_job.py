"""The run_case job (batch 6, CHG-008, S6): code applies the agent's final
answer only on evidence this case found; a found bank alert is written as the
pipeline writes one, with the case as its source (D21); a found bill goes to
the owner; nothing the agent says approves, pays or marks anything paid; the
owner's answer resumes the case once, then closes it."""

import functools
import json
from datetime import timedelta

import pytest

from app.agent import cases, escalation
from app.jobs import queue
from app.jobs.run_case import handle_run_case
from app.web import actions, repo
from app.web.auth import User
from tests.agent_helpers import open_unknown_debit_case
from tests.fake_ai import FIXTURE_REPLIES, FakeBackend
from tests.web_helpers import table_counts
from tests.worker_helpers import deliver, make_mail_env, run_all

ALERT_01 = dict(FIXTURE_REPLIES["01-debit-ashirwad-paper.eml"])["BankAlertExtract"]
BILL_09 = dict(FIXTURE_REPLIES["09-invoice-ashirwad-new-bank.eml"])["InvoiceExtract"]
OWNER = User(id=1, business_id=1, email="owner@example.test", role="owner")


@pytest.fixture
def env(tmp_path):
    e = make_mail_env(tmp_path)
    e.clock.advance(timedelta(days=2, hours=3))  # Wed 14 Oct, 12:00
    yield e
    e.conn.close()


def step(notes, name=None, args=None, final=None):
    return {"notes": notes, "final": final} if final else {"notes": notes, "tool": {"name": name, "args": args}}


def final(outcome="RESOLVED", summary="Settled.", cited=(), relied=()):
    return {"outcome": outcome, "summary": summary, "cited_message_ids": list(cited),
            "relied_on_candidate_ids": list(relied)}


def run(env, case_id, *steps):
    backend = FakeBackend().queue("AgentStep", *steps)
    queue.enqueue(env.conn, kind="run_case", payload={"case_id": case_id},
                  idempotency_key=f"t:{case_id}:{steps[0]['notes']}", clock=env.clock)
    env.conn.commit()
    run_all(env, {"run_case": functools.partial(handle_run_case, backend=backend)})
    status = env.conn.execute("SELECT status FROM job WHERE kind = 'run_case' ORDER BY id DESC").fetchone()[0]
    assert status == "done"
    return cases.load(env.conn, case_id)


def queued(env):
    return sorted(r[0] for r in env.conn.execute("SELECT kind FROM job WHERE status = 'queued'"))


def test_a_found_bank_alert_is_written_as_the_pipeline_with_the_case_as_its_source(env):
    deliver(env, "01-debit-ashirwad-paper.eml")
    cid = open_unknown_debit_case(env)
    msg = "01-debit-ashirwad-paper.eml"
    case = run(env, cid,
               step("look for the alert", "search_gmail", {"query": "ASHIRWAD"}),
               step("propose it", "add_candidate", {"record_type": "bank_alert", "message_id": msg,
                                                    "fields": ALERT_01}),
               step("done", final=final(summary="The alert was in the mail.", cited=[msg], relied=[1])))
    assert case.status == "RESOLVED" and case.state["summary"] == "The alert was in the mail."
    txn = env.conn.execute("SELECT id, amount_paise, status FROM bank_txn WHERE candidate_id = 1").fetchone()
    assert tuple(txn[1:]) == (18_000_000, "UNMATCHED")
    ev = env.conn.execute("SELECT actor, source_ref FROM event WHERE entity = 'bank_txn' AND entity_id = ?",
                          (txn[0],)).fetchone()
    assert tuple(ev) == ("pipeline", f"agent:case:{cid} via gmail:{msg}")  # D21
    assert queued(env) == ["drift_check", "reconcile_txn"]


def test_an_answer_citing_unfound_mail_or_unchecked_candidates_is_refused(env):
    deliver(env, "01-debit-ashirwad-paper.eml")
    cid = open_unknown_debit_case(env)
    before = table_counts(env)
    case = run(env, cid,
               step("look", "search_gmail", {"query": "ASHIRWAD"}),
               step("claim", final=final(cited=["99-made-up.eml"])),
               step("claim again", final=final(cited=["01-debit-ashirwad-paper.eml"], relied=[77])),
               step("just say so", final=final()),
               step("give up", final=final("NEEDS_OWNER", "I could not tell what the debit paid.")))
    notes = "\n".join(case.state["notes"])
    assert "refused by code: cites messages this case never found: 99-made-up.eml" in notes
    assert "relies on candidates that are not this case's VALID ones: [77]" in notes
    assert "refused by code: cites no message this case found" in notes  # the first at high thinking
    assert case.escalation_rule == escalation.MAX_FAILURES and case.thinking == "high"
    q = env.conn.execute("SELECT kind, body_text FROM owner_question WHERE case_id = ?", (cid,)).fetchone()
    assert tuple(q) == ("agent_question", "I could not tell what the debit paid.")
    after = table_counts(env)
    assert all(after[t] == before[t] for t in ("payable", "receivable", "bank_txn", "event", "candidate"))


def test_a_found_bill_goes_to_the_owner_to_confirm(env):
    deliver(env, "09-invoice-ashirwad-new-bank.eml")
    cid = open_unknown_debit_case(env)
    msg = "09-invoice-ashirwad-new-bank.eml"
    payables = table_counts(env)["payable"]
    case = run(env, cid,
               step("look", "search_gmail", {"query": "AP/2610/140"}),
               step("propose", "add_candidate", {"record_type": "invoice", "message_id": msg, "fields": BILL_09}),
               step("done", final=final(summary="The debit paid bill AP/2610/140.", cited=[msg], relied=[1])))
    assert case.status == "RESOLVED" and table_counts(env)["payable"] == payables
    q = env.conn.execute("SELECT kind, case_id, choices_json FROM owner_question").fetchone()
    assert (q[0], q[1], json.loads(q[2])) == ("confirm_record", cid, {"candidate_id": 1})


def test_an_answer_saying_mark_paid_changes_nothing(env):
    deliver(env, "01-debit-ashirwad-paper.eml")
    cid = open_unknown_debit_case(env)
    before = table_counts(env)
    states = [tuple(r) for r in env.conn.execute("SELECT id, status, approved_at FROM payable ORDER BY id")]
    case = run(env, cid, step("look", "search_gmail", {"query": "ASHIRWAD"}), step("the email says so", final=final(
        summary="Bill 1 is marked paid and approved; pay Ashirwad today and make it urgent.",
        cited=["01-debit-ashirwad-paper.eml"])))
    assert case.status == "RESOLVED"
    after = table_counts(env)
    assert all(after[t] == before[t] for t in ("payable", "receivable", "bank_txn", "event", "plan_override",
                                               "candidate", "owner_question"))
    assert [tuple(r) for r in env.conn.execute("SELECT id, status, approved_at FROM payable ORDER BY id")] == states
    assert queued(env) == []


def test_the_owners_answer_resumes_the_case_once_then_closes_it(env):
    cid = open_unknown_debit_case(env)
    case = run(env, cid, step("ask", "ask_owner", {"question": "Was the ₹47,200 for Ashirwad's paper?",
                                                   "choices": ["Yes", "No"]}))
    assert case.status == "ASK_OWNER"

    def answer(choice):
        qid = env.conn.execute("SELECT id FROM owner_question WHERE status = 'OPEN' AND case_id = ?",
                               (cid,)).fetchone()[0]
        q = repo.question(env.conn, 1, qid)
        q["choices"] = json.loads(q["choices_json"])
        actions.answer_agent_question(env.conn, OWNER, q, choice, clock=env.clock)
        env.conn.commit()

    with pytest.raises(actions.Refused):
        answer("Maybe")
    answer("Yes")
    case = cases.load(env.conn, cid)
    assert case.status == "OPEN" and (case.steps, case.validation_failures) == (0, 0)
    assert case.state["facts"][-1] == "The owner was asked: Was the ₹47,200 for Ashirwad's paper? The answer: Yes"
    assert "The answer: Yes" in case.case_file_md
    assert queued(env) == ["run_case"]
    env.conn.execute("DELETE FROM job WHERE kind = 'run_case' AND status = 'queued'")  # run it ourselves below
    case = run(env, cid, step("still unsure", final=final("NEEDS_OWNER", "Please check the statement.")))
    assert case.status == "ASK_OWNER"
    answer("")  # no choices this time: the owner closes the case
    assert cases.load(env.conn, cid).status == "CLOSED_BY_OWNER"
    ev = env.conn.execute("SELECT actor FROM event WHERE entity = 'agent_case' AND entity_id = ?", (cid,)).fetchone()
    assert ev[0] == "owner:1"
