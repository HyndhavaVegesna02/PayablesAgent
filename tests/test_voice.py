"""Voice notes (batch 5 plan, S6; CHG-007 AC3; PO requirement: "dedh lakh"
gives ₹1,50,000 through code, and no stored number comes from the model).
A voice note is read in one call, transcript and bill together; code turns
the spoken amount into paise; the owner confirms with the transcript beside
the form, and types an amount the code can't read."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.money import parse_spoken_inr
from app.ingest.store import DocumentStore
from app.web import actions, repo
from app.web.auth import User
from app.web.routes.attention import prefill
from app.worker import default_handlers
from tests.fake_ai import FakeBackend
from tests.web_helpers import login, make_web_env
from tests.worker_helpers import run_all

OWNER = User(1, 1, "owner@example.test", "owner")
HELPER = User(2, 1, "helper@example.test", "helper")
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt  a short voice note"
NOTE = {
    "transcript": "Ashirwad Paper ka naya bill aaya hai, dedh lakh rupaye, invoice AP/2610/150, "
                  "30 October tak dena hai.",
    "vendor_name": "Ashirwad Paper", "amount_spoken": "dedh lakh", "invoice_number": "AP/2610/150",
    "due_date": "2026-10-30", "uncertain_fields": [],
}


@pytest.mark.parametrize("said, paise", [
    ("dedh lakh", 15_000_000), ("Dedh lakh rupaye", 15_000_000), ("sawa lakh", 12_500_000),
    ("sawa do lakh", 22_500_000), ("dhai lakh", 25_000_000), ("saade teen lakh", 35_000_000),
    ("paune do lakh", 17_500_000), ("45 hazaar", 4_500_000), ("ek lakh pachaas hazaar", 15_000_000),
    ("one lakh fifty thousand", 15_000_000), ("2 lakh 40 hazaar", 24_000_000), ("1.5 lakh", 15_000_000),
    ("Rs.1,50,000", 15_000_000), ("dedh sau", 15_000), ("twenty five thousand", 2_500_000),
    ("ek lakh pachaas hazaar paanch sau", 15_050_000), ("do crore", 2_000_000_000),
])
def test_spoken_amounts_become_exact_paise(said, paise):
    got = parse_spoken_inr(said)
    assert got == paise and type(got) is int


@pytest.mark.parametrize("said", ["", "bahut saara", "lakh", "hazaar lakh", "dedh", "sawa", "saade lakh",
                                  "saade teen", "ek lakh do lakh", "0.00001 sau", "kuch zyada paise"])
def test_anything_else_is_refused_never_guessed(said):
    with pytest.raises(ValueError):
        parse_spoken_inr(said)


@given(st.integers(1, 99), st.integers(1, 99), st.integers(0, 9))
def test_lakh_hazaar_and_sau_add_up_exactly(lakh, hazaar, sau):
    said = f"{lakh} lakh {hazaar} hazaar" + (f" {sau} sau" if sau else "")
    assert parse_spoken_inr(said) == (lakh * 100_000 + hazaar * 1000 + sau * 100) * 100


@pytest.fixture
def web(tmp_path):
    env, client = make_web_env(tmp_path)
    yield env, client
    env.conn.close()


def send_note(env, reply, content=WAV):
    backend = FakeBackend().queue("VoiceBillExtract", reply)
    actions.upload(env.conn, HELPER, content, "voice", DocumentStore(env.settings.data_dir, env.settings.fernet_key),
                   clock=env.clock)
    run_all(env, default_handlers(backend))
    return backend


def test_a_voice_note_is_read_in_one_call_and_dedh_lakh_becomes_150000_through_code(web):
    env, client = web
    backend = send_note(env, NOTE)
    assert backend.calls("SortResult") == [] and len(backend.calls("VoiceBillExtract")) == 1
    assert backend.requests[0].contents[-1].mime_type == "audio/wav"
    cand = next(c for c in repo.waiting_candidates(env.conn, 1) if c["document_kind"] == "voice")
    assert (cand["record_type"], cand["status"]) == ("payable", "VALID")
    assert cand["record"]["amount_paise"] == 15_000_000 and cand["transcript"] == NOTE["transcript"]
    login(client)
    page = client.get("/attention").text
    assert "What was said:" in page and "dedh lakh rupaye" in page
    assert 'value="₹1,50,000"' in page  # the confirm form's amount, from code
    actions.confirm_candidate(env.conn, OWNER, cand["id"], prefill(cand, repo.accounts(env.conn, 1)), clock=env.clock)
    bill = env.conn.execute("SELECT amount_paise, status, due_date FROM payable WHERE invoice_number = 'AP/2610/150'"
                            ).fetchone()
    assert tuple(bill) == (15_000_000, "CONFIRMED", "2026-10-30")


def test_an_amount_the_code_cannot_read_goes_to_the_owner_at_once_with_the_transcript(web):
    env, _ = web
    backend = send_note(env, {**NOTE, "amount_spoken": "kuch zyada"})
    assert len(backend.calls("VoiceBillExtract")) == 1  # asking again cannot help (Q8)
    cand = next(c for c in repo.waiting_candidates(env.conn, 1) if c["document_kind"] == "voice")
    assert cand["status"] == "AWAITING_OWNER" and cand["record"]["amount_paise"] is None
    assert cand["checks"]["amount"] == ("failed: 'kuch zyada' is not an amount this app can read from what was said: "
                                     "type it in")
    assert prefill(cand, [])["amount"] == ""
    body = env.conn.execute("SELECT body_text FROM owner_question WHERE kind = 'confirm_record'").fetchone()[0]
    assert body.startswith("Please check this bill from an uploaded voice note: Ashirwad Paper.")


def test_the_voice_schema_carries_the_amount_only_as_words(web):
    from app.ai.extract import VoiceBillExtract

    props = VoiceBillExtract.model_json_schema()["properties"]
    assert "amount_spoken" in props and not any("paise" in k or "amount" == k for k in props)
