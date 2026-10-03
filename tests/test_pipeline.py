"""The mail pipeline end to end through the worker (batch 2 plan, CHG-004
AC1, AC2, AC4-AC6, AC10), on the seeded worked example with the fake AI.
Each test copies the fixtures it needs into its own inbox."""

import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from cryptography.fernet import Fernet

from app.ai.client import AIUnavailable
from app.ingest import pipeline
from app.ingest.store import KEYGEN_COMMAND
from app.jobs import queue
from app.trace import view
from app.worker import default_handlers
from tests.fake_ai import FIXTURE_REPLIES, FakeBackend, fixture_backend
from tests.worker_helpers import ROOT, deliver, make_mail_env
from tests.worker_helpers import run_all as _run_all

FIXTURES = ROOT / "fixtures" / "test_inbox"
DEBIT = "01-debit-ashirwad-paper.eml"
RETURN = "03-return-ashirwad-paper.eml"
OFFER = "05-offer-newsletter.eml"
RESENT = "06-debit-ashirwad-paper-resent.eml"
GOOD_ALERT = dict(FIXTURE_REPLIES[DEBIT])["BankAlertExtract"]


@pytest.fixture
def env(tmp_path):
    e = make_mail_env(tmp_path)
    e.clock.advance(timedelta(days=4, hours=1))  # Fri 16 Oct, 10:00: every fixture is released
    yield e
    e.conn.close()


def run_all(env, backend):
    _run_all(env, default_handlers(backend))


def poll(env, backend):
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    run_all(env, backend)


def rows(env, sql, *args):
    return env.conn.execute(sql, args).fetchall()


def job(env, kind):
    return rows(env, "SELECT * FROM job WHERE kind = ? ORDER BY id", kind)


# --- AC1: a bank alert becomes a transaction ------------------------------------------


def test_a_debit_alert_becomes_a_bank_txn_through_the_worker(env):
    deliver(env, DEBIT)
    poll(env, fixture_backend(DEBIT))

    (doc,) = rows(env, "SELECT * FROM source_document")
    assert (doc["kind"], doc["status"], doc["doc_type"]) == ("email", "PROCESSED", "bank_alert")
    assert doc["external_ref"] == "<instaalert-20261012-114207-4821-01@hdfcbank.example>"
    assert doc["received_at"] == "2026-10-12T11:42:07+05:30"

    (cand,) = rows(env, "SELECT * FROM candidate")
    assert (cand["status"], cand["attempts"], cand["record_type"], cand["created_by"]) == (
        "VALID", 1, "txn", "pipeline",
    )
    assert (cand["model_id"], cand["thinking"]) == ("gemini-3.8-flash", "medium")
    assert cand["prompt_version"] == "2026-10-02.1/extract_bank_alert.v1"
    assert set(json.loads(cand["checks_json"]).values()) == {"passed", "not_applicable"}

    (txn,) = rows(env, "SELECT * FROM bank_txn")
    assert (txn["account_id"], txn["direction"], txn["amount_paise"], txn["txn_date"]) == (
        1, "debit", 18_000_000, "2026-10-12",
    )
    assert (txn["counterparty"], txn["reference"], txn["balance_after_paise"]) == (
        "ASHIRWAD PAPER SUPPLIERS", "N286261234567", 44_000_000,
    )
    assert txn["dedup_key"] == "1:2026-10-12:debit:18000000:N286261234567"
    assert (txn["source_document_id"], txn["candidate_id"], txn["status"]) == (doc["id"], cand["id"], "UNMATCHED")

    (created,) = rows(env, "SELECT * FROM event WHERE event_type = 'BANK_TXN_CREATED'")
    process_job = job(env, "process_document")[0]
    assert created["actor"] == "pipeline"
    assert created["source_ref"] == f"source_document:{doc['id']}"
    assert created["trace_run_id"] == f"job-{process_job['id']}-attempt-1"

    (reconcile,) = job(env, "reconcile_txn")
    assert json.loads(reconcile["payload_json"]) == {"bank_txn_id": txn["id"]}
    assert reconcile["status"] == "done"  # CHG-005's handler ran it


def test_the_stored_email_is_encrypted_at_rest(env):
    deliver(env, DEBIT)
    poll(env, fixture_backend(DEBIT))
    (doc,) = rows(env, "SELECT storage_path FROM source_document")
    path = Path(env.settings.data_dir) / doc["storage_path"]
    data = path.read_bytes()
    assert b"ASHIRWAD" not in data and b"4821" not in data
    assert pipeline.document_store(env.settings).get(doc["storage_path"]) == (FIXTURES / DEBIT).read_bytes()


def test_what_gemini_sees_is_the_headers_and_text_not_our_fixture_note(env):
    deliver(env, DEBIT)
    backend = fixture_backend(DEBIT)
    poll(env, backend)
    sent = backend.requests[0].contents
    assert sent.startswith("From: HDFC Bank InstaAlerts <alerts@hdfcbank.example>\nDate: Mon, 12 Oct 2026")
    assert "Rs.1,80,000.00 has been debited from account **4821" in sent
    assert "X-Fixture-Note" not in sent and "fictional data" not in sent


# --- AC2: a readable trace --------------------------------------------------------------


def test_the_run_leaves_a_readable_trace(env, monkeypatch, capsys):
    deliver(env, DEBIT)
    poll(env, fixture_backend(DEBIT))
    process_job = job(env, "process_document")[0]
    monkeypatch.setenv("TRACE_DIR", env.settings.trace_dir)
    capsys.readouterr()

    assert view.main([f"job-{process_job['id']}-attempt-1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "tool=ai.call:sort" in out[0] and "model=gemini-3.8-flash(low)" in out[0]
    assert "tool=ai.call:extract:bank_alert" in out[1] and "model=gemini-3.8-flash(medium)" in out[1]
    for line in out[:2]:
        assert "tokens=input:1000/output:100/thoughts:50" in line
        assert "cost=1313µ$" in line
    assert "tool=validate" in out[2] and "'amount': 'passed'" in out[2]
    assert "tool=route" in out[3] and "reconcile_txn job" in out[3]


# --- AC4: checks, retry with the failures attached, escalate, ask the owner -----------------


def _alert(**over):
    return {**GOOD_ALERT, **over}


def test_a_failed_check_is_retried_with_the_failures_attached(env):
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", {"doc_type": "bank_alert", "reason": "r"})
    backend.queue("BankAlertExtract", _alert(amount_text="1.8 lakh"), GOOD_ALERT)
    poll(env, backend)

    extracts = backend.calls("BankAlertExtract")
    assert [r.thinking for r in extracts] == ["medium", "medium"]
    retry = extracts[1].contents
    assert "failed these checks:\n- amount: amount '1.8 lakh' is not an amount in rupees" in retry
    assert '"amount_text": "1.8 lakh"' in retry  # the previous answer, so it can correct itself
    (cand,) = rows(env, "SELECT status, attempts, thinking FROM candidate")
    assert tuple(cand) == ("VALID", 2, "medium")
    assert len(rows(env, "SELECT * FROM bank_txn")) == 1


def test_a_second_failure_is_extracted_at_high_thinking(env):
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", {"doc_type": "bank_alert", "reason": "r"})
    backend.queue("BankAlertExtract", "not json", _alert(account_last4="9999"), GOOD_ALERT)
    poll(env, backend)
    assert [r.thinking for r in backend.calls("BankAlertExtract")] == ["medium", "medium", "high"]
    assert tuple(rows(env, "SELECT status, attempts, thinking FROM candidate")[0]) == ("VALID", 3, "high")


@pytest.mark.parametrize("first_ok", [True, False])
def test_an_uncertain_field_goes_to_the_owner_without_asking_the_model_again(env, first_ok):
    # Whether it is unsure on the first reading or on a retry, the model is not
    # asked again, so it cannot drop the flag and slip the record past the owner.
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", {"doc_type": "bank_alert", "reason": "r"})
    unsure = _alert(uncertain_fields=["amount_text"])
    backend.queue("BankAlertExtract", *([unsure, GOOD_ALERT] if first_ok else [_alert(amount_text="?"), unsure,
                                                                              GOOD_ALERT]))
    poll(env, backend)
    expected_calls = 1 if first_ok else 2
    assert len(backend.calls("BankAlertExtract")) == expected_calls
    (cand,) = rows(env, "SELECT status, attempts, checks_json FROM candidate")
    assert (cand["status"], cand["attempts"]) == ("AWAITING_OWNER", expected_calls)
    assert json.loads(cand["checks_json"])["confidence"] == "failed: the model is unsure of amount_text"
    (q,) = rows(env, "SELECT kind, body_text FROM owner_question")
    assert q["kind"] == "confirm_record" and "confidence (the model is unsure of amount_text)" in q["body_text"]
    assert rows(env, "SELECT * FROM bank_txn") == []


def test_a_document_stored_under_another_key_dead_letters_at_once(env):
    deliver(env, DEBIT)
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    _run_all(env, {"poll_mail": pipeline.handle_poll_mail})  # stored, process_document queued
    env.settings = env.settings.model_copy(update={"fernet_key": Fernet.generate_key().decode()})
    run_all(env, FakeBackend())
    (j,) = job(env, "process_document")
    assert (j["status"], j["attempts"]) == ("dead", 1)
    assert "does not match the key these documents were stored with" in j["last_error"]


def test_a_third_failure_asks_the_owner_and_writes_nothing_to_the_ledger(env):
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", {"doc_type": "bank_alert", "reason": "r"})
    backend.queue("BankAlertExtract", *[_alert(account_last4="9999")] * 3)
    poll(env, backend)

    (cand,) = rows(env, "SELECT * FROM candidate")
    assert (cand["status"], cand["attempts"], cand["thinking"]) == ("AWAITING_OWNER", 3, "high")
    assert json.loads(cand["checks_json"])["account"] == "failed: no account of this business ends in 9999"
    (q,) = rows(env, "SELECT * FROM owner_question")
    assert (q["kind"], q["status"], q["business_id"]) == ("confirm_record", "OPEN", 1)
    assert "account (no account of this business ends in 9999)" in q["body_text"]
    assert json.loads(q["choices_json"]) == {"candidate_id": cand["id"]}
    assert rows(env, "SELECT * FROM bank_txn") == []
    assert job(env, "reconcile_txn") == []
    assert rows(env, "SELECT status FROM source_document")[0][0] == "PROCESSED"


# --- AC5: duplicates and unknown senders never reach the ledger ---------------------------


def test_a_resent_alert_with_a_new_message_id_is_a_duplicate_and_is_not_retried(env):
    deliver(env, DEBIT, RESENT)
    backend = fixture_backend(DEBIT, RESENT)
    poll(env, backend)

    assert len(rows(env, "SELECT * FROM source_document")) == 2
    assert len(rows(env, "SELECT * FROM bank_txn")) == 1
    second = rows(env, "SELECT * FROM candidate ORDER BY id")[1]
    assert (second["status"], second["attempts"]) == ("INVALID", 1)
    assert json.loads(second["checks_json"])["duplicates"] == "failed: same as bank transaction 1"
    assert len(backend.calls("BankAlertExtract")) == 2  # one each: re-reading cannot undo a duplicate
    assert len(job(env, "reconcile_txn")) == 1


def test_the_same_bytes_twice_or_a_second_poll_store_nothing_new(env):
    deliver(env, DEBIT)
    shutil.copy(FIXTURES / DEBIT, f"{env.settings.test_inbox_path}/01-copy.eml")
    poll(env, fixture_backend(DEBIT))
    poll(env, FakeBackend())  # nothing new: no AI call is made
    assert len(rows(env, "SELECT * FROM source_document")) == 1
    assert len(job(env, "process_document")) == 1
    assert len(rows(env, "SELECT * FROM bank_txn")) == 1


def test_mail_from_an_unknown_sender_is_never_fetched(env):
    raw = (FIXTURES / DEBIT).read_bytes().replace(b"alerts@hdfcbank.example", b"alerts@hdfc-secure.example")
    with open(f"{env.settings.test_inbox_path}/spoof.eml", "wb") as f:
        f.write(raw)
    poll(env, FakeBackend())
    assert rows(env, "SELECT * FROM source_document") == []


# --- AC6: irrelevant mail and failure notices --------------------------------------------


def test_an_irrelevant_email_stops_after_sort(env):
    deliver(env, OFFER)
    backend = fixture_backend(OFFER)
    poll(env, backend)
    (doc,) = rows(env, "SELECT status, doc_type FROM source_document")
    assert tuple(doc) == ("IRRELEVANT", "irrelevant")
    assert [r.json_schema["title"] for r in backend.requests] == ["SortResult"]
    assert rows(env, "SELECT * FROM candidate") == []


def test_a_return_email_queues_reconcile_failure(env):
    deliver(env, RETURN)
    poll(env, fixture_backend(RETURN))
    (cand,) = rows(env, "SELECT * FROM candidate")
    assert cand["status"] == "ACCEPTED"  # valid, then reconciled by reconcile_failure
    payload = json.loads(cand["payload_json"])
    assert payload["doc_type"] == "failure_notice"
    assert payload["record"] == {
        "account_id": 1, "amount_paise": 18_000_000, "failure_date": "2026-10-14",
        "original_reference": "N286261234567", "reason": "Beneficiary account closed or transferred",
        "dedup_key": "failure:1:2026-10-14:18000000:N286261234567",
    }
    (j,) = job(env, "reconcile_failure")
    assert json.loads(j["payload_json"]) == {"candidate_id": cand["id"]}
    assert rows(env, "SELECT * FROM bank_txn") == []


def test_document_types_not_read_yet_stop_after_sort_without_an_extract(env):
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", {"doc_type": "challan", "reason": "r"})
    poll(env, backend)
    assert tuple(rows(env, "SELECT status, doc_type FROM source_document")[0]) == ("PROCESSED", "challan")
    assert len(backend.requests) == 1


# --- failures of the job itself ----------------------------------------------------------


def test_a_blank_fernet_key_dead_letters_the_poll_and_says_how_to_make_one(env):
    env.settings = env.settings.model_copy(update={"fernet_key": ""})
    deliver(env, DEBIT)
    poll(env, FakeBackend())
    (j,) = job(env, "poll_mail")
    assert j["status"] == "dead"
    assert "FERNET_KEY is not set" in j["last_error"]
    assert KEYGEN_COMMAND in j["last_error"]
    assert ".env" in j["last_error"] and "GEMINI" not in j["last_error"]


def test_an_invalid_fernet_key_is_refused_without_echoing_it(env):
    env.settings = env.settings.model_copy(update={"fernet_key": "not-a-real-key-123"})
    deliver(env, DEBIT)
    poll(env, FakeBackend())
    (j,) = job(env, "poll_mail")
    assert j["status"] == "dead"
    assert "is not a valid Fernet key" in j["last_error"]
    assert "not-a-real-key-123" not in j["last_error"]


@pytest.mark.parametrize("retryable, status", [(True, "queued"), (False, "dead")])
def test_an_ai_outage_retries_or_gives_up_and_writes_nothing(env, retryable, status):
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", AIUnavailable("down", retryable=retryable))
    poll(env, backend)
    (j,) = job(env, "process_document")
    assert (j["status"], j["attempts"]) == (status, 1)
    assert rows(env, "SELECT * FROM candidate") == []
    assert rows(env, "SELECT status FROM source_document")[0][0] == "NEW"


def test_an_outage_mid_ladder_leaves_nothing_and_the_retry_starts_over(env):
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", {"doc_type": "bank_alert", "reason": "r"},
                                  {"doc_type": "bank_alert", "reason": "r"})
    backend.queue("BankAlertExtract", _alert(amount_text="?"), AIUnavailable("down", retryable=True),
                  GOOD_ALERT)
    poll(env, backend)
    assert rows(env, "SELECT * FROM candidate") == []
    env.clock.advance(timedelta(minutes=1))
    run_all(env, backend)
    (cand,) = rows(env, "SELECT status, attempts FROM candidate")
    assert tuple(cand) == ("VALID", 1)


def test_a_sort_reply_that_does_not_match_its_schema_is_retried(env):
    deliver(env, DEBIT)
    poll(env, FakeBackend().queue("SortResult", {"doc_type": "spam"}))
    (j,) = job(env, "process_document")
    assert (j["status"], j["attempts"]) == ("queued", 1)
    assert "sort reply did not match the schema" in j["last_error"]


def test_an_email_with_no_date_is_stored_as_failed_and_not_processed(env):
    raw = (FIXTURES / DEBIT).read_bytes()
    raw = b"".join(line for line in raw.splitlines(keepends=True) if not line.startswith(b"Date:"))
    with open(f"{env.settings.test_inbox_path}/nodate.eml", "wb") as f:
        f.write(raw)
    poll(env, FakeBackend())
    (doc,) = rows(env, "SELECT status FROM source_document")
    assert doc[0] == "FAILED"
    assert job(env, "process_document") == []


def test_polling_records_the_sync_time_and_looks_back_one_day(env):
    poll(env, FakeBackend())
    (state,) = rows(env, "SELECT * FROM sync_state")
    assert tuple(state) == ("eml_folder", env.clock.now().isoformat())
    assert pipeline._since(env.conn, "eml_folder", 1).isoformat() == "2026-10-15"


def test_mail_jobs_are_registered_only_with_an_ai_backend():
    assert {"poll_mail", "process_document"} <= set(default_handlers(FakeBackend()))
    assert not {"poll_mail", "process_document"} & set(default_handlers())


# --- contract grid: absent headers -------------------------------------------------------


def test_an_email_with_no_message_id_is_keyed_by_its_content_hash(env):
    raw = (FIXTURES / DEBIT).read_bytes()
    raw = b"".join(line for line in raw.splitlines(keepends=True) if not line.startswith(b"Message-ID:"))
    with open(f"{env.settings.test_inbox_path}/no-id.eml", "wb") as f:
        f.write(raw)
    poll(env, fixture_backend(DEBIT))
    (doc,) = rows(env, "SELECT external_ref, content_sha256, status FROM source_document")
    assert doc["external_ref"] == f"sha256:{doc['content_sha256']}"
    assert doc["status"] == "PROCESSED"
    poll(env, FakeBackend())  # seen again: skipped by the unique keys
    assert len(rows(env, "SELECT * FROM source_document")) == 1


def test_an_email_with_no_from_header_is_never_listed(env):
    raw = (FIXTURES / DEBIT).read_bytes()
    raw = b"".join(line for line in raw.splitlines(keepends=True) if not line.startswith(b"From:"))
    with open(f"{env.settings.test_inbox_path}/no-from.eml", "wb") as f:
        f.write(raw)
    poll(env, FakeBackend())
    assert rows(env, "SELECT * FROM source_document") == []


def test_an_alert_without_an_available_balance_queues_no_drift_check(env):
    deliver(env, DEBIT)
    backend = FakeBackend().queue("SortResult", {"doc_type": "bank_alert", "reason": "r"})
    backend.queue("BankAlertExtract", _alert(available_balance_text=None))
    poll(env, backend)
    assert rows(env, "SELECT balance_after_paise FROM bank_txn")[0][0] is None
    assert job(env, "drift_check") == []
    assert rows(env, "SELECT COUNT(*) FROM job WHERE status NOT IN ('done', 'queued')")[0][0] == 0


def test_a_refused_ai_call_leaves_googles_reason_in_the_job_without_the_key(env):
    import httpx

    from app.ai.client import GeminiBackend

    key = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE1234567"
    refuse = httpx.MockTransport(lambda req: httpx.Response(403, json={"error": {
        "code": 403, "status": "PERMISSION_DENIED", "message": f"Permission denied for key {key}"}}))
    backend = GeminiBackend(key, timeout_ms=1000, httpx_client=httpx.Client(transport=refuse))
    deliver(env, DEBIT)
    poll(env, backend)
    (j,) = job(env, "process_document")
    assert j["status"] == "dead"
    assert "Permission denied for key ***REDACTED-KEY***" in j["last_error"]
    assert key not in j["last_error"]
    for trace in Path(env.settings.trace_dir).rglob("*.jsonl"):
        assert key not in trace.read_text(encoding="utf-8")
