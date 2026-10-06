"""The agent can finish a drift case when the evidence is in the mailbox
(batch 8, CHG-031; found by the live pilot, scenario 07, and diagnosed from
its kept trace). There the agent found the missed alert, proposed it with
field names of its own, was told only "9 field error(s): Field required",
gave a RESOLVED answer relying on nothing, and the case went to the owner.
The fixes are in the harness: the prompt names the fields, a refusal names
what is wrong, an empty drift resolution is refused with how to fix it, the
case's facts say where to look, and a handed-on message keeps its case."""

import json

from app.ai.client import RawAIResponse
from app.ai.extract import BankAlertExtract, InvoiceExtract, InvoiceLine
from app.ai.fixture_backend import FixtureBackend
from evals import runner, scenario

MISSED = "11-debit-shree-transport-missed.eml"
# The missed alert as the canned drift script in fixtures/ai_replies.json reads it
RIGHT = {"account_last4": "4821", "direction": "debit", "amount_text": "Rs.20,000.00", "txn_date": "2026-10-13",
         "counterparty": "SHREE TRANSPORT", "reference": "628716051234", "available_balance_text": "Rs.6,00,000.00",
         "uncertain_fields": []}
# The live model's own fields (docs/evals/3-improvement-and-regression/live-pilot-before/traces/
# 07-missed-alert-causes-drift-run1, job 11)
WRONG = {"account": "4821", "account_mask": "XXXX4821", "amount": "Rs.20,000.00", "counterparty": "SHREE TRANSPORT",
         "party": "SHREE TRANSPORT", "date": "2026-10-13", "txn_date": "2026-10-13", "direction": "debit",
         "reference": "628716051234"}
SEARCH = {"notes": "Search the alert sender's mail.",
          "tool": {"name": "search_gmail", "args": {"query": "alerts@hdfcbank.example"}}}
PROPOSE_WRONG = {"notes": "Propose the missed alert.", "tool": {"name": "add_candidate", "args": {
    "record_type": "bank_alert", "message_id": MISSED, "fields": WRONG}}}
PROPOSE_RIGHT = {"notes": "Use the fields the refusal named.", "tool": {"name": "add_candidate", "args": {
    "record_type": "bank_alert", "message_id": MISSED, "fields": RIGHT}}}
RESOLVE = {"notes": "The missed debit explains the gap.", "final": {
    "outcome": "RESOLVED", "summary": "A missed Rs.20,000.00 debit to SHREE TRANSPORT on 13 Oct.",
    "cited_message_ids": [MISSED], "relied_on_candidate_ids": [3]}}  # 1 is the pipeline's, 2 refused
GIVE_UP = {"notes": "Not sure.", "final": {"outcome": "NEEDS_OWNER", "summary": "Found an alert, could not use it.",
                                           "cited_message_ids": [], "relied_on_candidate_ids": []}}


def test_the_prompt_names_every_field_add_candidate_takes():
    text = (runner.ROOT / "app" / "ai" / "prompts" / "exception_agent.v1.md").read_text(encoding="utf-8")
    for model in (BankAlertExtract, InvoiceExtract, InvoiceLine):
        assert [f for f in model.model_fields if f not in text] == [], model.__name__
    assert "fix it and try again" in text and "by the sender" in text


class ScriptedDriftCase(FixtureBackend):
    """Scenario 07's canned world, with the drift case worked by these steps.
    The pipeline's own reading of the missed alert, if it is handed on, is
    canned here too: in scenario 07 the pipeline never reads it otherwise."""

    def __init__(self, *steps):
        super().__init__()
        self.steps = list(steps)
        self.case_files: list[str] = []

    def generate(self, *, model, system, contents, thinking, json_schema):
        title = (json_schema or {}).get("title")
        if title == "AgentStep" and "gap in account" in contents:
            self.case_files.append(contents)
            return RawAIResponse(json.dumps(self.steps.pop(0)), 0, 0, 0)
        text = contents if isinstance(contents, str) else " ".join(c for c in contents if isinstance(c, str))
        if title in ("SortResult", "BankAlertExtract") and "SHREE TRANSPORT" in text:
            reply = RIGHT if title == "BankAlertExtract" else {"doc_type": "bank_alert", "reason": "a debit alert"}
            return RawAIResponse(json.dumps(reply), 0, 0, 0)
        return super().generate(model=model, system=system, contents=contents, thinking=thinking,
                                json_schema=json_schema)


def _play(backend):
    seen = {}

    def inspect(env):
        one = lambda sql: env.conn.execute(sql).fetchone()  # noqa: E731
        seen.update(
            case=dict(one("SELECT id, status, thinking, escalation_rule FROM agent_case WHERE kind = 'drift'")),
            first_candidate=json.loads(one("SELECT checks_json FROM candidate WHERE created_by LIKE 'agent:case:%' "
                                           "ORDER BY id")[0]),
            txn=dict(one("SELECT t.source_document_id, e.source_ref FROM bank_txn t JOIN event e ON e.entity = "
                         "'bank_txn' AND e.entity_id = t.id AND e.event_type = 'BANK_TXN_CREATED' "
                         "WHERE t.counterparty = 'SHREE TRANSPORT'")),
            drift=one("SELECT drift_status FROM bank_account WHERE id = 1")[0])
        return {}

    r = runner.run_once(scenario.load("07-missed-alert-causes-drift"), backend, runner.load_config(None)[0],
                        inspect=inspect)
    return r, seen


def test_a_replay_of_the_live_mistake_now_resolves_the_case_at_medium():
    backend = ScriptedDriftCase(SEARCH, PROPOSE_WRONG, PROPOSE_RIGHT, RESOLVE)
    r, seen = _play(backend)
    assert r.status == "PASSED", [(c.id, c.got) for c in r.checks if not c.ok]
    assert backend.steps == []  # every scripted step was used, the refused call included
    schema = seen["first_candidate"]["schema"]
    assert schema.startswith("failed: missing account_last4, amount_text, available_balance_text, "
                             "uncertain_fields; not fields of this record: account, account_mask, amount, date, party")
    assert schema.endswith("Its fields are: account_last4, direction, amount_text, txn_date, counterparty, reference, "
                           "available_balance_text, uncertain_fields")
    case = seen["case"]
    assert (case["status"], case["thinking"], case["escalation_rule"]) == ("RESOLVED", "medium", None)
    assert seen["txn"]["source_ref"] == f"agent:case:{case['id']} via gmail:{MISSED}"  # D21
    assert seen["drift"] == "OK"
    facts = backend.case_files[0]
    assert "The bank's alert senders for this account: alerts@hdfcbank.example" in facts
    assert "A missing debit of ₹20,000, or several adding up to it, would explain the gap" in facts
    assert "Dates to look between: " in facts


def test_a_message_the_agent_found_but_could_not_apply_is_written_with_its_case():
    """The pilot's own path: the run ends without applying the alert it found.
    The pipeline reads the handed-on message, and the debit's source still
    names the case (D21). Asking the owner then stays safe."""
    r, seen = _play(ScriptedDriftCase(SEARCH, PROPOSE_WRONG, GIVE_UP))
    case, txn = seen["case"], seen["txn"]
    assert txn["source_ref"] == f"agent:case:{case['id']} via gmail:{MISSED} via source_document:{txn['source_document_id']}"
    assert case["status"] == "ASK_OWNER"
