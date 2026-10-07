"""The shrimp-farm demo profile (batch 21, CHG-058; dev only): a second,
additive profile for Demo Day. Its settings come from .env.shrimp applied as
process environment, never by touching .env; its config and canned replies
are its own files beside the worked example's; its seed only ever writes
./data/shrimp.db; and the rehearsal driver plays moves 1 to 6 through the real
routes, worker and demo clock, offline for free."""

import hashlib
import html
import json
import sys
from datetime import datetime

import pytest

from app import worker
from app.ai.extract import InvoiceExtract, VoiceBillExtract
from app.ai.fixture_backend import FixtureBackend, load_replies
from app.clock import FakeClock
from app.config import Settings, load_app_config
from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from app.jobs.replan import replan
from app.main import create_app
from app.validate.invoice import check_invoice
from app.validate.voice import check_voice
from evals.workflow import ROOT, _text
from fixtures import shrimp_seed
from scripts import rehearse_shrimp, with_env

# The tests play the PLACEHOLDER uploads: the user's real files are untracked and on one machine only (PO), so no
# test depends on them being there.
PLACEHOLDERS = {which: rehearse_shrimp.UPLOADS / name for which, name in rehearse_shrimp.PLACEHOLDER.items()}


@pytest.fixture
def placeholders_only(monkeypatch):
    monkeypatch.setattr(rehearse_shrimp, "REAL", {"voice": "no-such-voice-file", "photo": "no-such-photo-file"})


def play(tmp_path, backend=None):
    """The offline fortnight on the placeholders, with `backend` (the canned replies by default)."""
    run = rehearse_shrimp.ShrimpRun(tmp_path, backend or FixtureBackend(rehearse_shrimp.REPLIES),
                                    load_app_config(rehearse_shrimp.CONFIG), fixtures_mode=True, uploads=PLACEHOLDERS)
    try:
        rehearse_shrimp.fortnight(run)
        return run, {"rejected": [tuple(r) for r in run.conn.execute(
            "SELECT d.external_ref, c.status FROM candidate c JOIN source_document d ON d.id = c.source_document_id "
            "WHERE c.status = 'REJECTED' ORDER BY c.id")],
            "buyer_bills": run.one("SELECT COUNT(*) FROM payable p JOIN party pt ON pt.id = p.party_id "
                                   "WHERE pt.name = 'Ravi Traders'")}
    finally:
        run.close()


SHRIMP_SENDERS = ["accounts@srilakshmiaquafeeds.example", "ravi@ravitraders.example", "subbarao@example.test"]


# --- AC1: the two settings ------------------------------------------------------------------------------


def test_the_profile_settings_default_to_the_worked_examples_files(monkeypatch):
    for name in ("APP_CONFIG_PATH", "FIXTURE_REPLIES_PATH"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert (s.app_config_path, s.fixture_replies_path) == ("config.yaml", "")


def test_the_process_environment_overrides_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("APP_CONFIG_PATH=from-dotenv.yaml\nFIXTURE_REPLIES_PATH=from-dotenv.json\n", encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_PATH", "config.shrimp.yaml")
    monkeypatch.delenv("FIXTURE_REPLIES_PATH", raising=False)
    s = Settings(_env_file=dotenv)
    assert (s.app_config_path, s.fixture_replies_path) == ("config.shrimp.yaml", "from-dotenv.json")


def test_the_web_app_loads_the_config_the_setting_names(monkeypatch):
    monkeypatch.chdir(ROOT)
    app = create_app(Settings(_env_file=None, session_secret="t", app_config_path="config.shrimp.yaml"))
    assert app.state.app_config.mail.vendor_senders == SHRIMP_SENDERS


def test_the_worker_loads_the_config_the_setting_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here: only the environment speaks
    monkeypatch.setenv("APP_CONFIG_PATH", "config.shrimp.yaml")
    asked = []

    def stop(path):
        asked.append(path)
        raise SystemExit(0)

    monkeypatch.setattr(worker, "load_app_config", stop)
    with pytest.raises(SystemExit):
        worker.main()
    assert asked == ["config.shrimp.yaml"]


def test_the_worker_answers_from_the_store_the_setting_names(tmp_path):
    settings = Settings(_env_file=None, demo_now="2026-10-19T09:00:00+05:30", demo_ai="fixtures",
                        fixture_replies_path=str(ROOT / "fixtures" / "shrimp_ai_replies.json"))
    backend, config = worker.build_backend(settings, load_app_config(ROOT / "config.shrimp.yaml"))
    assert "03-credit-ravi-k-upi.eml" in backend.texts and "01-debit-ashirwad-paper.eml" not in backend.texts
    assert config.model.id == "fixture-ai"
    default, _ = worker.build_backend(settings.model_copy(update={"fixture_replies_path": ""}),
                                      load_app_config(ROOT / "config.yaml"))
    assert "01-debit-ashirwad-paper.eml" in default.texts and "03-credit-ravi-k-upi.eml" not in default.texts


# --- AC3: the profile's files, beside the worked example's -----------------------------------------------


def test_the_shrimp_config_is_config_yaml_with_the_profiles_senders():
    shrimp, base = load_app_config(ROOT / "config.shrimp.yaml"), load_app_config(ROOT / "config.yaml")
    assert shrimp.mail.vendor_senders == SHRIMP_SENDERS
    assert shrimp.model_copy(update={"mail": base.mail}) == base  # nothing else differs


def test_every_shrimp_email_and_upload_has_a_canned_reply_and_the_worked_examples_store_has_none():
    store = ROOT / "fixtures" / "shrimp_ai_replies.json"
    backend = FixtureBackend(store)
    emails = sorted(p.name for p in (ROOT / "fixtures" / "shrimp_inbox").glob("*.eml"))
    assert len(emails) == 8 and sorted(backend.texts) == emails
    assert all("SortResult" in backend.email_replies[name] for name in emails)
    assert sorted(load_replies("shrimp_uploads", store)) == sorted(
        [*rehearse_shrimp.PLACEHOLDER.values(), *REAL_FILES])  # the real ones answer where the files are (CHG-061)
    placeholder_hashes = {hashlib.sha256(path.read_bytes()).hexdigest() for path in PLACEHOLDERS.values()}
    assert placeholder_hashes <= set(backend.file_replies)
    assert not set(FixtureBackend().texts) & set(emails)


# The user's delta (batch 22, CHG-060): move 4 is two different bills, one per input path. The caretaker's Telugu
# voice note (amount and date said in English: the parser reads no Telugu numbers) and Venkat Motors' slip.
DIESEL_SCRIPT = ("Raju petrol bunk diesel bill, generator kosam, three thousand rupees, twenty-fourth October 2026 "
                 "lopala kattali.")


def test_the_placeholder_voice_note_reads_as_raju_petrol_bunks_diesel_bill_and_passes_every_check():
    reply = load_replies("shrimp_uploads", ROOT / "fixtures" / "shrimp_ai_replies.json")[
        rehearse_shrimp.PLACEHOLDER["voice"]]["VoiceBillExtract"]
    assert reply["transcript"] == DIESEL_SCRIPT
    checks, record, reading = check_voice(VoiceBillExtract.model_validate(reply), None, lambda key: None)
    assert record is not None, checks  # nothing for the owner to type
    assert (reading["party"], reading["amount_paise"], reading["due_date"]) == ("Raju Petrol Bunk", 300_000,
                                                                              "2026-10-24")


def test_the_placeholder_slip_reads_as_venkat_motors_repair_bill_and_passes_every_check():
    reply = load_replies("shrimp_uploads", ROOT / "fixtures" / "shrimp_ai_replies.json")[
        rehearse_shrimp.PLACEHOLDER["photo"]]["InvoiceExtract"]
    checks, record, reading = check_invoice(InvoiceExtract.model_validate(reply), None, "Godavari Aqua Farm",
                                            lambda key: None)
    assert record is not None, checks
    assert (reading["party"], reading["invoice_number"], reading["amount_paise"], reading["due_date"]) == (
        "Venkat Motors", "VM/412", 1_800_000, "2026-10-25")  # 14,000 rewinding + 4,000 bearings and oil
    assert checks["gstin"] == "not_applicable" and checks["invoice_arithmetic"] == "passed"


def test_the_scripted_agent_cites_the_message_that_explains_each_credit():
    scripts = {s["case"]: s for s in json.loads((ROOT / "fixtures" / "shrimp_ai_replies.json").read_text(
        encoding="utf-8"))["agent_scripts"]}
    assert set(scripts) == {"Credit of ₹2,00,000", "Credit of ₹9,20,000"}
    finals = [r["step"]["final"] for s in scripts.values() for r in s["rules"] if "final" in r["step"]]
    assert [f["cited_message_ids"] for f in finals] == [["02-weighment-slip-ravi-traders.eml"],
                                                        ["06-payment-advice-ravi-traders.eml"]]
    assert all(f["relied_on_candidate_ids"] == [] for f in finals)  # nothing for code to write: the owner links


# --- AC2: .env.shrimp, applied as process environment ----------------------------------------------------


def test_the_profile_env_files_carry_no_secret():
    shrimp = with_env.environment([str(ROOT / ".env.shrimp")])
    assert shrimp["DATABASE_PATH"] == "./data/shrimp.db" and shrimp["APP_CONFIG_PATH"] == "config.shrimp.yaml"
    assert shrimp["DEMO_AI"] == "" and shrimp["SMTP_HOST"] == ""  # live AI; no alert email leaves the machine
    fallback = with_env.environment([str(ROOT / ".env.shrimp"), str(ROOT / ".env.shrimp-fixtures")])
    assert (fallback["DEMO_AI"], fallback["FIXTURE_REPLIES_PATH"]) == ("fixtures", "fixtures/shrimp_ai_replies.json")
    for name in (".env.shrimp", ".env.shrimp-fixtures"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not [s for s in with_env.SECRETS if f"\n{s}=" in f"\n{text}"]


@pytest.mark.parametrize("line", ["GEMINI_API_KEY=", "session_secret=abc", "SMTP_PASSWORD=x"])
def test_a_secret_in_a_profile_is_refused(line):
    with pytest.raises(with_env.Refused, match="belongs in .env only"):
        with_env.parse([line], "f")


def test_later_files_and_arguments_win_and_the_command_gets_them(tmp_path, capfd):
    a, b = tmp_path / "a.env", tmp_path / "b.env"
    a.write_text("# c\nX_ONE=a\nX_TWO=a\n", encoding="utf-8")
    b.write_text("X_TWO=b\n", encoding="utf-8")
    code = with_env.main([str(a), str(b), "X_THREE=arg", "--", sys.executable, "-c",
                          "import os; print(os.environ['X_ONE'], os.environ['X_TWO'], os.environ['X_THREE'])"])
    assert code == 0 and capfd.readouterr().out.split() == ["a", "b", "arg"]


def test_the_make_targets_apply_the_profile_and_never_name_dotenv():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "SHRIMP_ENV = .env.shrimp $(if $(FALLBACK),.env.shrimp-fixtures)" in text
    recipes = {t: text.split(f"\n{t}:\n", 1)[1].splitlines()[0]
               for t in ("run-shrimp", "worker-shrimp", "reseed-shrimp", "demo-time-shrimp")}
    assert all(r.startswith("\tuv run python scripts/with_env.py $(SHRIMP_ENV)") for r in recipes.values())
    assert "DATABASE_PATH=./data/shrimp.db -- python -m fixtures.shrimp_seed --fresh" in recipes["reseed-shrimp"]
    assert not [r for r in recipes.values() if " .env " in f"{r} "]


# --- the seed --------------------------------------------------------------------------------------------


def test_the_shrimp_seed_plans_the_monday_before_the_harvest(tmp_path):
    db = tmp_path / "s.db"
    apply_migrations(db)
    conn = write_connection(db)
    try:
        clock = FakeClock(datetime.fromisoformat(rehearse_shrimp.START))
        shrimp_seed.seed(conn, clock)
        replan(conn, 1, triggered_by="seed", clock=clock)
        conn.commit()
        assert conn.execute("SELECT name, safety_amount_paise, payment_days FROM business").fetchone()[:] == (
            "Godavari Aqua Farm", 5_000_000, "MON,THU")
        assert conn.execute("SELECT bank_account_mask, bank_ifsc, bank_status FROM party WHERE id = 1").fetchone()[:] \
            == ("XXXX2201", "SBIN0004321", "verified")
        assert [tuple(r) for r in conn.execute("SELECT invoice_number, confidence FROM receivable ORDER BY id")] == [
            ("HARVEST-ADV", "COMMITTED"), ("HARVEST-BAL", "EXPECTED")]
        run = conn.execute("SELECT lowest_balance_paise, lowest_on, valid FROM plan_run WHERE is_current = 1").fetchone()
        assert tuple(run) == (11_000_000, "2026-10-19", 1)
    finally:
        conn.close()


def test_the_shrimp_seed_refuses_any_database_but_its_own(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    other = tmp_path / "cashflow.db"
    other.write_bytes(b"the worked example's database")
    monkeypatch.setenv("DATABASE_PATH", str(other))
    monkeypatch.setenv("DEMO_NOW", rehearse_shrimp.START)
    assert shrimp_seed.main(["--fresh"]) == 2
    assert other.read_bytes() == b"the worked example's database"
    assert "only writes ./data/shrimp.db" in capsys.readouterr().err


def test_the_shrimp_seed_refuses_another_data_dir_so_no_other_demo_clock_is_reset(tmp_path, monkeypatch, capsys):
    # The profile's own paths point into tmp, so even a broken guard can't touch the real ./data/shrimp.db.
    monkeypatch.chdir(tmp_path)
    profile_db = tmp_path / "shrimp.db"
    monkeypatch.setattr(shrimp_seed, "SHRIMP_DB", profile_db)
    monkeypatch.setattr(shrimp_seed, "SHRIMP_FILES", tmp_path / "shrimp-files")
    worked_example_clock = tmp_path / "files" / "demo_clock.txt"
    worked_example_clock.parent.mkdir()
    worked_example_clock.write_text("2026-10-15T09:00:00+05:30", encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(profile_db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("DEMO_NOW", rehearse_shrimp.START)
    assert shrimp_seed.main(["--fresh"]) == 2
    assert worked_example_clock.read_text(encoding="utf-8") == "2026-10-15T09:00:00+05:30"
    assert not profile_db.exists()  # refused before any database was made
    assert "./data/shrimp-files" in capsys.readouterr().err


# --- AC4: the rehearsal driver ---------------------------------------------------------------------------


def test_the_rehearsal_passes_every_move_offline(tmp_path, placeholders_only):
    assert rehearse_shrimp.main(["--ai", "fixtures", "--out", str(tmp_path)]) == 0
    (folder,) = tmp_path.iterdir()
    data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert data["ok"] and [m["action"].split(",")[0] for m in data["moves"]] == [
        "Start", "Move 1", "Move 2", "Move 3", "Move 4", "Move 5", "Move 6"]
    ids = [c["id"] for m in data["moves"] for c in m["checks"]]
    assert {"checklist-5-advance-matched", "checklist-5-advance-confirmed", "checklist-5-balance-confirmed",
            "checklist-5-gap-named", "checklist-5-floor-holds"} <= set(ids)
    assert ids.count("agent-finding-shown") == 2 and ids.count("nothing-preselected") == 2
    assert all(c["why"] for m in data["moves"] for c in m["checks"])
    assert data["meta"]["uploads"] == ["voice: PLACEHOLDER-voice-note.wav", "photo: PLACEHOLDER-repair-slip.png"]
    assert "## 7. Move 6" in (folder / "report.md").read_text(encoding="utf-8")
    move4 = {c["id"] for c in data["moves"][4]["checks"]}
    assert {"voice-bill", "slip-bill", "two-bills-not-one", "transcript-beside-it", "lease-not-paid-early",
            "new-bills-in-the-plan", "thursday-approved"} <= move4  # paid on time (PO)
    assert "one-repair-bill" not in move4  # the owner rejects nothing (CHG-060)
    for n, ref in ((2, "02"), (5, "06")):  # which path each buyer's record took is in the report (CHG-061)
        assert "no-bill-from-the-buyer" in {c["id"] for c in data["moves"][n]["checks"]}
        assert f"{ref} sorted as payment_confirmation: no bill to reject" in data["moves"][n]["notes"]


# What docs/demo-shrimp.md quotes, each as the owner's pages render it in the offline fortnight (AC5).
QUOTED = [
    "You stay above your safety amount for the next 14 days. Lowest: ₹1,10,000 on Mon 19 Oct.",
    "Bank details on this bill: account ending 2201, IFSC SBIN0004321",
    "A ₹2,00,000 credit on Tue 20 Oct from RAVI K (ravi.k@okaxis) (reference 629312345678) was not matched to an "
    "invoice. Which invoice did it pay, if any?",
    "ravi@ravitraders.example: Purchase record and weighment slip: your harvest of 20 Oct, advance paid",
    "The assistant's words. They change nothing: only the invoice you choose does.",
    "Ravi Traders HARVEST-ADV ₹2,00,000 (counted in the plan, expected on Tue 20 Oct)",
    "A bill from Sri Lakshmi Aqua Feeds gives different bank details: account ending 8876, IFSC ICIC0007788 (on "
    "record: account ending 2201, IFSC SBIN0004321).",
    "₹5,16,800 below your safety amount on Thu 29 Oct",
    "Lowest balance -₹4,66,800 on Thu 29 Oct",
    "Sri Lakshmi Aqua Feeds needs your decision. Pick how to cover the gap.",
    "Ask Ravi Traders to pay ₹10,15,000 by Wed 21 Oct",
    "Split Sri Lakshmi Aqua Feeds: ₹2,05,000 now, ₹4,41,800 due Wed 4 Nov",
    "Asked by Wed 21 Oct; not received",
    "A ₹9,20,000 credit on Fri 23 Oct from RAVI TRADERS (reference N296271234567) was not matched to an invoice.",
    "Ravi Traders HARVEST-BAL ₹10,15,000 (not counted in the plan, expected on Fri 30 Oct; short by ₹95,000)",
    "Lowest: ₹4,32,200 on Thu 29 Oct.",
    # move 4, the user's delta (CHG-060): two bills, both confirmed
    "Please check this bill from an uploaded voice note: Raju Petrol Bunk, ₹3,000.",
    "Please check this bill from an uploaded photo: Venkat Motors, ₹18,000.",
    "generator kosam, three thousand rupees, twenty-fourth October 2026 lopala kattali.",
    "You're approving 4 payments, ₹51,000",
    "You pay them in your bank app; we never move money.",
    "Lowest balance -₹4,87,800 on Thu 29 Oct",
    "starting from ₹5,83,200 in your bank accounts",
    "AI replies are canned fixtures.",
]
EVENT = "Owner: this ₹9,20,000 credit settles Ravi Traders HARVEST-BAL, short by ₹95,000 (₹10,15,000 invoiced)."


def test_what_the_demo_script_quotes_is_what_the_pages_render(tmp_path):
    pages = []

    class Watching(rehearse_shrimp.ShrimpRun):
        def drain(self):  # after every worker run: each move, and each confirm, link and approval within one
            super().drain()
            pages.extend(html.unescape(_text(self.owner.get(p))) for p in ("/", "/attention"))

    run = Watching(tmp_path, FixtureBackend(rehearse_shrimp.REPLIES), load_app_config(rehearse_shrimp.CONFIG),
                   fixtures_mode=True, uploads=PLACEHOLDERS)
    try:
        rehearse_shrimp.fortnight(run)
        events = [r[0] for r in run.conn.execute("SELECT reason FROM event WHERE event_type = 'RECEIVABLE_CONFIRMED'")]
    finally:
        run.close()
    assert all(s.ok for s in run.steps)
    seen = " ".join(pages)
    doc = (ROOT / "docs" / "demo-shrimp.md").read_text(encoding="utf-8")
    script = " ".join(doc.replace("\n> ", "\n").split())  # a quote may run over lines of a blockquote
    assert [q for q in QUOTED if q not in seen] == []
    assert [q for q in QUOTED if q not in script] == []
    assert EVENT in events and EVENT in script


def test_the_users_real_files_replace_the_placeholders_live_and_offline_only_once_they_have_replies(
        tmp_path, monkeypatch):
    monkeypatch.setattr(rehearse_shrimp, "UPLOADS", tmp_path)
    for name in rehearse_shrimp.PLACEHOLDER.values():
        (tmp_path / name).write_bytes(b"placeholder")
    (tmp_path / "voice-diesel-raju.wav").write_bytes(b"RIFF real")  # the delta's names (CHG-060)
    (tmp_path / "voice-note-lakshman.ogg").write_bytes(b"OggS the earlier name")  # no longer picked up
    live, _ = rehearse_shrimp.uploads_for(True)
    offline, said = rehearse_shrimp.uploads_for(False)
    assert (live["voice"].name, live["photo"].name) == ("voice-diesel-raju.wav", "PLACEHOLDER-repair-slip.png")
    (tmp_path / "repair-slip-venkat.jpg").write_bytes(b"\xff\xd8\xff real")
    assert rehearse_shrimp.uploads_for(True)[0]["photo"].name == "repair-slip-venkat.jpg"
    assert offline["voice"].name == "PLACEHOLDER-voice-note.wav"  # no canned reply for the real file yet
    assert said == ["voice: PLACEHOLDER-voice-note.wav", "photo: PLACEHOLDER-repair-slip.png"]


def test_move_4_finds_the_two_bills_however_the_model_spells_their_vendors(tmp_path):
    # Live, the slip's header is in capitals and the transcript in lower case (batch 22 review): the ledger treats
    # "VENKAT MOTORS" and "Venkat Motors" as one name, so the rehearsal's checks must too.
    import copy

    backend = FixtureBackend(rehearse_shrimp.REPLIES)
    backend.file_replies = copy.deepcopy(backend.file_replies)
    for replies in backend.file_replies.values():
        if "InvoiceExtract" in replies:
            replies["InvoiceExtract"]["seller_name"] = LIVE_SLIP_VENDOR  # live rehearsal 1 read the whole header
        if "VoiceBillExtract" in replies:
            replies["VoiceBillExtract"]["vendor_name"] = "raju petrol bunk"
    run, _ = play(tmp_path, backend)
    move4 = run.steps[4]
    assert move4.ok, (move4.error, [(c.id, c.expected, c.actual) for c in move4.checks if not c.ok])
    assert all(s.ok for s in run.steps)


# --- live rehearsal 1's findings (batch 23, CHG-061) --------------------------------------------------------

LIVE_SLIP_VENDOR = "VENKAT MOTORS/Aerator & Pump Repairs, Bhimavaram"
REAL_FILES = ["voice-diesel-raju.mp3", "repair-slip-venkat.jpg"]
# What live rehearsal 1 read in the buyer's weighment slip: a ₹12,15,000 "bill from Ravi Traders", no due date.
MISREAD_02 = {"SortResult": {"doc_type": "invoice", "reason": "A weighment slip with a gross value."},
              "InvoiceExtract": {"seller_name": "Ravi Traders", "seller_gstin": None, "buyer_name": "Godavari Aqua Farm",
                                 "buyer_gstin": None, "invoice_number": None, "invoice_date": "2026-10-20",
                                 "due_date": None, "lines": [{"description": "Vannamei, 4,500 kg at Rs.270/kg",
                                                              "amount_text": "Rs.12,15,000.00"}],
                                 "gst_texts": [], "round_off_text": None, "total_text": "Rs.12,15,000.00",
                                 "payee_account_number": None, "payee_ifsc": None, "uncertain_fields": []}}


def test_a_waiting_bill_is_found_by_its_amount_and_number_never_by_its_place_in_the_queue(tmp_path):
    from fixtures.shrimp_seed import seed

    db = tmp_path / "s.db"
    apply_migrations(db)
    conn = write_connection(db)
    try:
        seed(conn, FakeClock(datetime.fromisoformat(rehearse_shrimp.START)))
        for n, (party, number, paise) in enumerate((("Ravi Traders", None, 121_500_000),  # first in the queue
                                                    ("Sri Lakshmi Aqua Feeds", "SLAF/INV/1042", 64_680_000)), 1):
            conn.execute("INSERT INTO source_document (id, business_id, kind, external_ref, content_sha256, received_at, "
                         "status) VALUES (?, 1, 'email', ?, ?, '2026-10-21T11:00:00+05:30', 'PROCESSED')",
                         (n, f"<m{n}>", f"{n:064d}"))
            conn.execute("INSERT INTO candidate (source_document_id, record_type, payload_json, status, created_by, "
                         "created_at) VALUES (?, 'payable', ?, 'AWAITING_OWNER', 'pipeline', '2026-10-21T11:00:00+05:30')",
                         (n, json.dumps({"record": {"party": party, "invoice_number": number, "amount_paise": paise}})))
        conn.commit()
        run = rehearse_shrimp.ShrimpRun.__new__(rehearse_shrimp.ShrimpRun)
        run.conn = conn
        second = conn.execute("SELECT id FROM candidate WHERE source_document_id = 2").fetchone()[0]
        assert rehearse_shrimp.waiting_bill(run, {"amount": "6,46,800", "invoice_number": "SLAF/INV/1042"}) == second
        assert rehearse_shrimp.waiting_bill(run, {"amount": "6,46,800", "invoice_number": "slaf inv 1042"}) == second
        with pytest.raises(rehearse_shrimp.StepFailed, match="no waiting bill"):
            rehearse_shrimp.waiting_bill(run, {"amount": "6,46,800", "invoice_number": "SLAF/INV/9999"})
    finally:
        conn.close()


def test_the_buyers_records_read_as_bills_are_rejected_and_the_fortnight_holds(tmp_path):
    import copy

    backend = FixtureBackend(rehearse_shrimp.REPLIES)
    backend.email_replies = copy.deepcopy(backend.email_replies)
    backend.email_replies["02-weighment-slip-ravi-traders.eml"] = MISREAD_02
    misread_06 = copy.deepcopy(MISREAD_02)  # the payment advice read as a bill too: the same rule holds
    misread_06["InvoiceExtract"].update(invoice_date="2026-10-23", total_text="Rs.9,20,000.00", lines=[
        {"description": "Harvest balance, net", "amount_text": "Rs.9,20,000.00"}])
    backend.email_replies["06-payment-advice-ravi-traders.eml"] = misread_06
    run, found = play(tmp_path, backend)
    assert all(s.ok for s in run.steps), [(s.action[:8], s.error, [(c.id, c.expected, c.actual) for c in s.checks
                                                                  if not c.ok]) for s in run.steps if not s.ok]
    assert found["buyer_bills"] == 0
    assert found["rejected"] == [("<shrimp-02@ravitraders.example>", "REJECTED"),
                                 ("<shrimp-06@ravitraders.example>", "REJECTED")]
    assert "02 sorted as invoice: the owner rejected the ₹12,15,000 bill from Ravi Traders" in run.steps[2].notes
    assert "06 sorted as invoice: the owner rejected the ₹9,20,000 bill from Ravi Traders" in run.steps[5].notes


def test_the_buyers_records_say_so_in_their_first_lines():
    def first_lines(name, n=4):
        body = (ROOT / "fixtures" / "shrimp_inbox" / name).read_text(encoding="utf-8").split("\n\n", 1)[1]
        return " ".join(line.strip() for line in body.strip().splitlines()[:n])

    slip, advice = first_lines("02-weighment-slip-ravi-traders.eml"), first_lines("06-payment-advice-ravi-traders.eml")
    for text in (slip, advice):
        assert "Ravi Traders pays Godavari Aqua Farm" in text and "Nothing is payable by the farm" in text
    assert "Advance Rs.2,00,000 paid today by UPI from ravi.k@okaxis." in slip  # the agent's snippet cut at "Adva"
    assert "Net paid: Rs.9,20,000.00 by NEFT today." in advice
    backend = FixtureBackend(rehearse_shrimp.REPLIES)  # the canned replies still answer the reworded mail
    for name, sorted_as in (("02-weighment-slip-ravi-traders.eml", "payment_confirmation"),
                            ("06-payment-advice-ravi-traders.eml", "payment_confirmation")):
        reply = backend.generate(model="fixture-ai", system="s", contents=f"From: x\n\n{backend.texts[name]}",
                                 thinking="low", json_schema={"title": "SortResult"})
        assert json.loads(reply.text)["doc_type"] == sorted_as


def test_the_real_files_replies_replay_what_live_rehearsal_1_read():
    replies = load_replies("shrimp_uploads", ROOT / "fixtures" / "shrimp_ai_replies.json")
    voice, slip = replies["voice-diesel-raju.mp3"]["VoiceBillExtract"], replies["repair-slip-venkat.jpg"]
    assert voice["transcript"] == "Raju petrol bunk diesel bill generator kosam 3000 rupees 24th October 2026 lopala kattali"
    checks, record, reading = check_voice(VoiceBillExtract.model_validate(voice), None, lambda key: None)
    assert record is not None and (reading["party"], reading["amount_paise"], reading["due_date"]) == (
        "Raju petrol bunk", 300_000, "2026-10-24")
    assert slip["SortResult"]["doc_type"] == "invoice"
    checks, record, reading = check_invoice(InvoiceExtract.model_validate(slip["InvoiceExtract"]), None,
                                            "Godavari Aqua Farm", lambda key: None)
    assert record is not None and (reading["party"], reading["invoice_number"], reading["amount_paise"],
                                   reading["due_date"]) == (LIVE_SLIP_VENDOR, "VM/412", 1_800_000, "2026-10-25")


def test_a_live_rehearsal_will_not_start_without_yes_spend(tmp_path):
    with pytest.raises(SystemExit, match="--yes-spend"):
        rehearse_shrimp.main(["--ai", "live", "--out", str(tmp_path)])
    assert list(tmp_path.iterdir()) == []


def test_rehearsals_are_git_ignored():
    assert "\n/rehearsals/\n" in (ROOT / ".gitignore").read_text(encoding="utf-8")
