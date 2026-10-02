"""Add: typed entries and uploads, for the owner and the helper (batch 3 plan,
CHG-006 S3; AC2: a helper sees only their own submissions)."""

import hashlib
import json
from pathlib import Path

import pytest

from app.ingest.store import DocumentStore
from fixtures.seed import _password_hash
from tests.web_helpers import HELPER, OWNER, login, make_web_env, post, table_counts

BILL = {"kind": "bill", "party": "Sharma Packaging", "invoice_number": "SP-7", "amount": "1,20,000",
        "due_date": "2026-11-05", "priority": "normal"}


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def _add_helper(env, user_id=4, email="helper2@example.test"):
    env.conn.execute("INSERT INTO app_user (id, business_id, email, role, password_hash) VALUES (?, 1, ?, 'helper', ?)",
                     (user_id, email, _password_hash("helper2-pass")))
    env.conn.commit()
    return email, "helper2-pass"


def test_a_helper_entry_becomes_a_typed_document_and_a_candidate(web):
    env, client = web
    csrf = login(client, HELPER)
    assert post(client, "/entries", csrf, BILL).status_code == 303
    doc = env.conn.execute("SELECT * FROM source_document").fetchone()
    assert (doc["kind"], doc["submitted_by"], doc["status"]) == ("typed", 2, "PROCESSED")
    cand = env.conn.execute("SELECT * FROM candidate").fetchone()
    assert (cand["record_type"], cand["status"], cand["created_by"]) == ("payable", "VALID", "user:2")
    record = json.loads(cand["payload_json"])["record"]
    assert record == {"kind": "bill", "party": "Sharma Packaging", "invoice_number": "SP-7", "invoice_date": None,
                      "amount_paise": 12_000_000, "due_date": "2026-11-05", "priority": "normal"}
    checks = json.loads(cand["checks_json"])
    assert checks["dates"] == checks["duplicates"] == "passed"
    assert env.conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0] == 5  # nothing in the ledger yet
    assert "Waiting for the owner to confirm" in client.get("/add").text


@pytest.mark.parametrize("text", ["1,20,000", "Rs.1,20,000", "₹ 1,20,000", "120000", "INR 120,000"])
def test_amounts_are_read_as_written(web, text):
    env, client = web
    csrf = login(client)
    post(client, "/entries", csrf, {**BILL, "amount": text})
    (payload,) = env.conn.execute("SELECT payload_json FROM candidate").fetchone()
    assert json.loads(payload)["record"]["amount_paise"] == 12_000_000


@pytest.mark.parametrize("change, field", [
    ({"amount": ""}, "amount"), ({"amount": "1.2 lakh"}, "amount"), ({"amount": "0"}, "amount"),
    ({"due_date": ""}, "due_date"), ({"due_date": "5/11/2026"}, "due_date"), ({"party": ""}, "party"),
    ({"priority": "urgent"}, "priority"),
])
def test_a_missing_or_unreadable_field_stores_nothing(web, change, field):
    env, client = web
    csrf = login(client, HELPER)
    before = table_counts(env)
    r = post(client, "/entries", csrf, {**BILL, **change})
    assert r.status_code == 422 and f'id="err-{field}"' in r.text
    assert table_counts(env) == before


def test_the_same_entry_twice_is_caught_by_the_duplicates_check(web):
    env, client = web
    csrf = login(client, HELPER)
    post(client, "/entries", csrf, BILL)
    r = post(client, "/entries", csrf, BILL)
    assert r.status_code == 422 and "already waiting for confirmation" in r.text
    assert env.conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 1


def test_a_bill_already_in_the_ledger_is_caught(web):
    env, client = web
    csrf = login(client)
    r = post(client, "/entries", csrf, {**BILL, "party": "M/S Prime Chem Industries Pvt Ltd",
                                        "invoice_number": "PRIME-001"})
    assert r.status_code == 422 and "invoice PRIME-001 is already recorded" in r.text


def test_a_helper_sees_only_their_own_submissions(web):
    env, client = web
    other = _add_helper(env)
    post(client, "/entries", login(client, HELPER), {**BILL, "party": "Helper One Vendor"})
    post(client, "/entries", login(client, other), {**BILL, "party": "Helper Two Vendor"})
    post(client, "/entries", login(client, OWNER), {**BILL, "party": "Owner Vendor"})

    login(client, HELPER)
    page = client.get("/add").text
    assert "Helper One Vendor" in page
    assert "Helper Two Vendor" not in page and "Owner Vendor" not in page
    assert "Lowest projected balance" not in page and "Prime Chem" not in page  # no plan, no other bills

    login(client, OWNER)
    page = client.get("/add").text
    assert all(name in page for name in ("Helper One Vendor", "Helper Two Vendor", "Owner Vendor"))


def test_an_upload_is_stored_encrypted_and_waits_for_reading(web):
    env, client = web
    csrf = login(client, HELPER)
    content = b"%PDF-1.4 fictional vendor bill"
    r = client.post("/uploads", data={"csrf_token": csrf}, files={"file": ("bill.pdf", content, "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    doc = env.conn.execute("SELECT * FROM source_document").fetchone()
    assert (doc["kind"], doc["status"], doc["submitted_by"]) == ("pdf", "NEW", 2)
    assert doc["content_sha256"] == hashlib.sha256(content).hexdigest()
    stored = Path(env.settings.data_dir) / doc["storage_path"]
    assert content not in stored.read_bytes()
    assert DocumentStore(env.settings.data_dir, env.settings.fernet_key).get(doc["storage_path"]) == content
    assert env.conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 0  # reading it is CHG-007
    assert "Waiting to be read" in client.get("/add").text


@pytest.mark.parametrize("name, ctype, kind", [("p.jpg", "image/jpeg", "photo"), ("v.ogg", "audio/ogg", "voice"),
                                               ("x.pdf", "application/octet-stream", "pdf")])
def test_upload_kinds_come_from_the_content_type(web, name, ctype, kind):
    env, client = web
    csrf = login(client)
    client.post("/uploads", data={"csrf_token": csrf}, files={"file": (name, b"data " + name.encode(), ctype)})
    assert env.conn.execute("SELECT kind FROM source_document").fetchone()[0] == kind


def test_an_upload_that_is_not_a_photo_pdf_or_voice_note_is_refused(web):
    env, client = web
    csrf = login(client)
    r = client.post("/uploads", data={"csrf_token": csrf}, files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 422
    assert env.conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0] == 0


def test_an_upload_over_10_mb_is_413(web):
    env, client = web
    csrf = login(client)
    big = b"0" * (10 * 1024 * 1024 + 1)
    r = client.post("/uploads", data={"csrf_token": csrf}, files={"file": ("big.pdf", big, "application/pdf")})
    assert r.status_code == 413
    assert env.conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0] == 0


def test_the_same_file_twice_is_refused(web):
    env, client = web
    csrf = login(client)
    for expected in (303, 409):
        r = client.post("/uploads", data={"csrf_token": csrf}, files={"file": ("a.pdf", b"same", "application/pdf")},
                        follow_redirects=False)
        assert r.status_code == expected
    assert env.conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0] == 1


def test_uploads_without_a_fernet_key_are_refused_with_a_plain_message(tmp_path):
    env, _ = make_web_env(tmp_path)
    from app.main import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app(env.settings.model_copy(update={"fernet_key": ""}), clock=env.clock,
                                   app_config=env.app_config))
    csrf = login(client)
    r = client.post("/uploads", data={"csrf_token": csrf}, files={"file": ("a.pdf", b"x", "application/pdf")})
    assert r.status_code == 409 and "FERNET_KEY is missing" in r.text
    env.conn.close()
