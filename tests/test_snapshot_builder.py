"""build_snapshot against a real migrated DB: one test per non-trivial cell of
the contract grid (batch 1 plan, CHG-003 "Contracts consumed")."""

from datetime import date, datetime

import pytest

from app.db.connection import write_connection
from app.db.migrate import apply_migrations
from app.db.read import build_snapshot, parse_payment_days, read_only_connection
from app.domain.models import BankTxnNew
from app.ledger import writer
from app.ledger.writer import EntityRef
from app.planner.plan import AccountCash, InflowIn, canonical_json, plan
from fixtures.seed import seed
from tests.ledger_helpers import make_ledger_db
from tests.planner_fixtures import TODAY, oct, worked_example


@pytest.fixture
def conn(tmp_path):
    c = make_ledger_db(tmp_path / "snap.db")
    yield c
    c.close()


def _exec(conn, sql, *args):
    conn.execute(sql, args)
    conn.commit()


def _payable(conn, status="CONFIRMED", **cols):
    values = {"business_id": 1, "amount_paise": 1_000, "due_date": "2026-10-15",
              "priority": "normal", "status": status, **cols}
    names = ", ".join(values)
    _exec(conn, f"INSERT INTO payable ({names}) VALUES ({', '.join('?' for _ in values)})",
          *values.values())


def _receivable(conn, confidence, expected_date, amount=1_000, business_id=1):
    _exec(conn, "INSERT INTO receivable (business_id, amount_paise, expected_date, confidence) "
                "VALUES (?, ?, ?, ?)", business_id, amount, expected_date, confidence)


# --- the seeded worked example ---------------------------------------------------


def test_seeded_database_gives_exactly_the_hand_built_golden_snapshot(tmp_path):
    db = tmp_path / "seeded.db"
    apply_migrations(db)
    w = write_connection(db)
    seed(w)
    w.close()
    ro = read_only_connection(db)
    try:
        assert build_snapshot(ro, 1, TODAY) == worked_example()
    finally:
        ro.close()


def test_seed_to_plan_gives_the_golden_bytes(tmp_path):
    db = tmp_path / "seeded.db"
    apply_migrations(db)
    w = write_connection(db)
    seed(w)
    w.close()
    ro = read_only_connection(db)
    try:
        assert canonical_json(plan(build_snapshot(ro, 1, TODAY))) == canonical_json(plan(worked_example()))
    finally:
        ro.close()


# --- business ----------------------------------------------------------------------


def test_missing_business_raises(conn):
    with pytest.raises(LookupError):
        build_snapshot(conn, 99, TODAY)


def test_zero_safety_is_a_valid_floor(conn):
    _exec(conn, "UPDATE business SET safety_amount_paise = 0 WHERE id = 1")
    assert build_snapshot(conn, 1, TODAY).safety_paise == 0


@pytest.mark.parametrize("horizon", [0, -3])
def test_non_positive_horizon_raises(conn, horizon):
    _exec(conn, "UPDATE business SET horizon_days = ? WHERE id = 1", horizon)
    with pytest.raises(ValueError):
        build_snapshot(conn, 1, TODAY)


def test_payment_days_parse():
    assert parse_payment_days("MON,THU") == frozenset({0, 3})
    assert parse_payment_days("SUN") == frozenset({6})
    assert parse_payment_days("") == frozenset()


@pytest.mark.parametrize("bad", ["MONDAY", "mon", "MON, THU", "MON,,THU"])
def test_unknown_payment_day_tokens_are_refused(conn, bad):
    _exec(conn, "UPDATE business SET payment_days = ? WHERE id = 1", bad)
    with pytest.raises(ValueError):
        build_snapshot(conn, 1, TODAY)


def test_empty_payment_days_means_every_bill_waits(conn):
    _exec(conn, "UPDATE business SET payment_days = '' WHERE id = 1")
    _payable(conn)
    s = build_snapshot(conn, 1, TODAY)
    assert s.payment_days == frozenset()
    assert [line.decision for line in plan(s).lines] == ["WAIT"]


def test_today_must_be_a_date_not_a_datetime(conn):
    with pytest.raises(TypeError):
        build_snapshot(conn, 1, datetime(2026, 10, 12, 9, 0))


# --- accounts ------------------------------------------------------------------------


def test_calculated_balance_counts_transactions_but_not_reversed_ones(conn):
    for key, status_after in (("t1", None), ("t2", "REVERSED")):
        t = writer.create_bank_txn(
            BankTxnNew(account_id=1, direction="debit", amount_paise=1_000_000,
                       txn_date=date(2026, 10, 12), dedup_key=key, status="UNMATCHED"),
            actor="pipeline", reason="t", source_ref=None, conn=conn,
        )
        if status_after:
            ref = EntityRef("bank_txn", t.id)
            writer.transition(ref, "MATCHED", "reconciler", "t", None, conn=conn)
            writer.transition(ref, "REVERSED", "reconciler", "t", None, conn=conn)
    (account,) = build_snapshot(conn, 1, TODAY).accounts
    assert account == AccountCash(1, 61_000_000, None, False)


def test_a_business_with_no_accounts_has_no_cash(conn):
    _exec(conn, "INSERT INTO business (id, name, safety_amount_paise) VALUES (3, 'B3', 0)")
    s = build_snapshot(conn, 3, TODAY)
    assert (s.accounts, plan(s).opening_cash_paise) == ((), 0)


def test_reported_zero_under_drift_is_a_real_zero(conn):
    _exec(conn, "UPDATE bank_account SET reported_balance_paise = 0, drift_status = 'CHECKING' WHERE id = 1")
    s = build_snapshot(conn, 1, TODAY)
    assert s.accounts == (AccountCash(1, 62_000_000, 0, True),)
    assert plan(s).opening_cash_paise == 0


def test_no_reported_balance_under_drift_uses_calculated(conn):
    _exec(conn, "UPDATE bank_account SET drift_status = 'ASK_OWNER' WHERE id = 1")
    s = build_snapshot(conn, 1, TODAY)
    assert s.accounts == (AccountCash(1, 62_000_000, None, True),)
    assert plan(s).opening_cash_paise == 62_000_000


def test_reported_balance_is_ignored_when_drift_is_ok(conn):
    _exec(conn, "UPDATE bank_account SET reported_balance_paise = 5 WHERE id = 1")
    s = build_snapshot(conn, 1, TODAY)
    assert s.accounts == (AccountCash(1, 62_000_000, 5, False),)
    assert plan(s).opening_cash_paise == 62_000_000


# --- payables --------------------------------------------------------------------------


def test_only_plannable_statuses_are_read(conn):
    for status in ("DRAFT", "CONFIRMED", "PLANNED", "PAYMENT_EXPECTED", "PAID", "REOPENED",
                   "REVIEW", "SPLIT"):
        _payable(conn, status, planned_date="2026-10-15" if status != "DRAFT" else None)
    statuses = [p.status for p in build_snapshot(conn, 1, TODAY).payables]
    assert statuses == ["CONFIRMED", "PLANNED", "PAYMENT_EXPECTED", "REOPENED"]


def test_no_payables_means_no_lines(conn):
    s = build_snapshot(conn, 1, TODAY)
    assert (s.payables, plan(s).lines) == ((), ())


def test_payables_of_other_businesses_are_not_read(conn):
    _payable(conn, business_id=2)
    assert build_snapshot(conn, 1, TODAY).payables == ()


def test_payment_expected_keeps_its_planned_date(conn):
    _payable(conn, "PAYMENT_EXPECTED", planned_date="2026-10-15")
    (p,) = build_snapshot(conn, 1, TODAY).payables
    assert (p.status, p.planned_date) == ("PAYMENT_EXPECTED", oct(15))


def test_malformed_due_date_raises(conn):
    _payable(conn, due_date="15/10/2026")
    with pytest.raises(ValueError, match="payable"):
        build_snapshot(conn, 1, TODAY)


def test_negative_grace_days_raises(conn):
    _payable(conn, grace_days=-1)
    with pytest.raises(ValueError, match="grace_days"):
        build_snapshot(conn, 1, TODAY)


@pytest.mark.parametrize(
    "discount, by, expected",
    [(None, None, (None, None)), (0, "2026-10-14", (None, None)), (50, None, (None, None)),
     (50, "2026-10-14", (50, oct(14)))],
)
def test_discount_absent_empty_or_present(conn, discount, by, expected):
    _payable(conn, discount_paise=discount, discount_by=by)
    (p,) = build_snapshot(conn, 1, TODAY).payables
    assert (p.discount_paise, p.discount_by) == expected


@pytest.mark.parametrize("discount", [1_000, 5_000])
def test_discount_at_or_above_the_bill_raises(conn, discount):
    _payable(conn, discount_paise=discount, discount_by="2026-10-14")
    with pytest.raises(ValueError, match="discount"):
        build_snapshot(conn, 1, TODAY)


# --- receivables ---------------------------------------------------------------------------


def test_receivables_split_into_counted_and_uncounted(conn):
    _receivable(conn, "COMMITTED", "2026-10-13")   # inside the horizon: counted
    _receivable(conn, "COMMITTED", "2026-10-25")   # last horizon day: counted
    _receivable(conn, "COMMITTED", "2026-10-26")   # after the horizon: uncounted
    _receivable(conn, "COMMITTED", "2026-10-11")   # promise date passed: neither
    _receivable(conn, "EXPECTED", "2026-10-14")    # EXPECTED: never counted
    _receivable(conn, "UNKNOWN", "2026-10-14")     # not read
    _receivable(conn, "CONFIRMED", "2026-10-14")   # already in the bank balance
    _receivable(conn, "COMMITTED", None)           # no date to count or move
    _receivable(conn, "COMMITTED", "2026-10-14", business_id=2)  # other business
    s = build_snapshot(conn, 1, TODAY)
    assert s.inflows == (
        InflowIn(1, 1_000, oct(13), "COMMITTED"),
        InflowIn(2, 1_000, oct(25), "COMMITTED"),
    )
    assert s.uncounted_inflows == (
        InflowIn(3, 1_000, oct(26), "COMMITTED"),
        InflowIn(5, 1_000, oct(14), "EXPECTED"),
    )
    assert s.commitments == ()


def test_no_receivables_means_no_inflows(conn):
    s = build_snapshot(conn, 1, TODAY)
    assert (s.inflows, s.uncounted_inflows) == ((), ())


class _CommitsAfterTheAccountsQuery:
    """Wraps a connection; a concurrent writer commits right after the accounts read."""

    def __init__(self, conn, on_accounts_read):
        self._conn = conn
        self._fire = on_accounts_read

    @property
    def in_transaction(self):
        return self._conn.in_transaction

    def execute(self, sql, args=()):
        cur = self._conn.execute(sql, args)
        if self._fire and "JOIN account_balance" in sql:
            fire, self._fire = self._fire, None
            fire()
        return cur

    def rollback(self):
        self._conn.rollback()


def test_snapshot_is_one_consistent_read_even_if_a_write_lands_midway(tmp_path):
    db = tmp_path / "race.db"
    w = make_ledger_db(db)
    _payable(w, "PAYMENT_EXPECTED", amount_paise=30_000_000, planned_date="2026-10-15")

    def owner_pays_and_the_debit_arrives():
        t = writer.create_bank_txn(
            BankTxnNew(account_id=1, direction="debit", amount_paise=30_000_000,
                       txn_date=date(2026, 10, 12), dedup_key="race", status="UNMATCHED"),
            actor="pipeline", reason="t", source_ref=None, conn=w,
        )
        writer.transition(EntityRef("bank_txn", t.id), "MATCHED", "reconciler", "t", None, conn=w)
        writer.transition(EntityRef("payable", 1), "PAID", "reconciler", "t", None, conn=w,
                          fields={"matched_txn_id": t.id})

    ro = read_only_connection(db)
    try:
        s = build_snapshot(_CommitsAfterTheAccountsQuery(ro, owner_pays_and_the_debit_arrives), 1, TODAY)
    finally:
        ro.close()
        w.close()
    # Before the write: ₹6,20,000 in the bank and ₹3,00,000 still expected to leave.
    assert s.accounts == (AccountCash(1, 62_000_000, None, False),)
    assert [(p.payable_id, p.status) for p in s.payables] == [(1, "PAYMENT_EXPECTED")]
    assert plan(s).lowest_balance_paise == 32_000_000


def test_malformed_expected_date_raises(conn):
    _receivable(conn, "COMMITTED", "next week")
    with pytest.raises(ValueError, match="receivable"):
        build_snapshot(conn, 1, TODAY)


def test_builder_works_on_a_read_only_connection(tmp_path):
    db = tmp_path / "ro.db"
    make_ledger_db(db).close()
    ro = read_only_connection(db)
    try:
        s = build_snapshot(ro, 1, TODAY)
    finally:
        ro.close()
    assert s.payables == () and s.accounts == (AccountCash(1, 62_000_000, None, False),)

