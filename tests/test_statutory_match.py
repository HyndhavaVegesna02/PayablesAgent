"""Statutory debits match by payee words (batch 8, CHG-028, D27): a statutory
bill has no party, so its challan debit is matched by the payee words of its
tax types (config.yaml, matching.statutory_payees), the same amount and the
same window, as a vendor's bill is by its names. On the seeded worked example:
PFESI-OCT26 (PF and ESI, ₹45,000, Thu 15) and GST-OCT26 (₹90,000, Mon 19)."""

from datetime import date

import pytest

from app.config import load_app_config
from app.domain.models import TaxObligationNew
from app.ledger import writer
from app.ledger.reconcile import match_debit
from app.ledger.writer import EntityRef
from tests.reconcile_helpers import GST, PFESI, cases, plan_and_approve, status, txn
from tests.worker_helpers import make_env

PAYEES = load_app_config().matching.statutory_payees


@pytest.fixture
def env(tmp_path):
    e = make_env(tmp_path)
    yield e
    e.conn.close()


def _debit(env, txn_id):
    return match_debit(env.conn, txn_id, window_days=3, clock=env.clock, statutory_payees=PAYEES)


def test_the_config_names_payee_words_for_every_tax_type():
    assert set(PAYEES) == {"GST", "TDS", "PF", "ESI", "ADVANCE_TAX"}
    assert PAYEES["PF"] == ["EPFO"] and PAYEES["ESI"] == ["ESIC"] and "CBIC" in PAYEES["GST"]


def test_a_pf_and_esi_challan_debit_pays_the_statutory_bill_by_itself(env):
    plan_and_approve(env, PFESI)
    t = txn(env, "debit", 4_500_000, date(2026, 10, 15), "EPFO ESIC CHALLAN")
    result = _debit(env, t)
    assert result.outcome == f"matched bill {PFESI}: PAID"
    assert status(env, "payable", PFESI) == "PAID" and status(env, "bank_txn", t) == "MATCHED"
    actor = env.conn.execute("SELECT actor FROM event WHERE entity = 'payable' AND entity_id = ? "
                             "AND event_type = 'PAYABLE_PAID'", (PFESI,)).fetchone()[0]
    assert actor == "reconciler" and cases(env) == []


def test_a_gst_challan_debit_pays_the_gst_bill(env):
    plan_and_approve(env, GST)
    t = txn(env, "debit", 9_000_000, date(2026, 10, 19), "GST CHALLAN CBIC")
    assert _debit(env, t).outcome == f"matched bill {GST}: PAID"


def test_two_statutory_bills_of_the_same_amount_go_to_review(env):
    second = writer.create_tax_obligation(
        TaxObligationNew(business_id=1, tax_type="PF", period="2026-09-arrears", due_date=date(2026, 10, 15),
                         amount_paise=4_500_000, amount_status="CONFIRMED"),
        actor="owner:1", reason="test: PF arrears of the same amount", source_ref=None, conn=env.conn,
        clock=env.clock).payable_id
    writer.transition(EntityRef("payable", second), "CONFIRMED", "owner:1", "test", None, conn=env.conn,
                      expected_version=1, clock=env.clock)
    plan_and_approve(env, PFESI, second)
    t = txn(env, "debit", 4_500_000, date(2026, 10, 15), "EPFO ESIC CHALLAN")
    result = _debit(env, t)
    assert result.outcome.startswith("ambiguous (several bills match this debit)")
    assert status(env, "payable", PFESI) == "REVIEW" and status(env, "payable", second) == "REVIEW"
    (case,) = cases(env)
    assert case["kind"] == "ambiguous_match" and "payee names ['EPFO', 'ESIC']" in case["case_file_md"]


def test_a_debit_naming_no_payee_word_still_asks_the_owner(env):
    plan_and_approve(env, PFESI)
    t = txn(env, "debit", 4_500_000, date(2026, 10, 15), "NEFT SALARY ADVANCE")
    assert _debit(env, t).outcome.startswith("ambiguous (a bill has this amount and date but not this payee's name)")
    assert status(env, "payable", PFESI) == "REVIEW"


def test_a_payee_word_without_the_amount_matches_nothing(env):
    plan_and_approve(env, PFESI)
    t = txn(env, "debit", 4_400_000, date(2026, 10, 15), "EPFO ESIC CHALLAN")
    assert _debit(env, t).outcome == "no bill matches: debit stays UNMATCHED"
    assert status(env, "payable", PFESI) == "PAYMENT_EXPECTED"


def test_a_payee_word_matches_whole_words_only(env):
    plan_and_approve(env, GST)
    t = txn(env, "debit", 9_000_000, date(2026, 10, 19), "GSTARCOM LOGISTICS")  # 'GST' inside another word
    assert _debit(env, t).outcome.startswith("ambiguous")
    assert status(env, "payable", GST) == "REVIEW"
