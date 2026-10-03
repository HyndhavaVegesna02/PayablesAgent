"""Owner alerts by email (batch 7, CHG-010b): code raises an alert at the
TDD's four owner events, and send_alert sends the unsent ones as one
fixed-template email to the owner's address in the database, at most once per
throttle window, over a separate SMTP account. Tests use an in-process fake
SMTP server; nothing leaves the machine."""

from datetime import timedelta

import pytest

from app.jobs import alerts, queue
from app.notify import smtp, templates
from app.worker import default_handlers
from tests.fake_ai import fixture_backend
from tests.worker_helpers import deliver, make_mail_env, run_all


class FakeSMTP:
    """Records what would have been sent; refuses when told to."""

    sent: list = []
    fail = False

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        self.tls = True

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise OSError("connection refused")
        FakeSMTP.sent.append((self.host, self.port, msg))


@pytest.fixture
def env(tmp_path):
    e = make_mail_env(tmp_path)
    e.settings = e.settings.model_copy(update={
        "smtp_host": "smtp.example.test", "smtp_port": 587, "smtp_user": "alerts-sender", "smtp_password": "pw",
        "alert_from": "alerts@example.test", "app_base_url": "https://cash.example.test"})
    FakeSMTP.sent, FakeSMTP.fail = [], False
    yield e
    e.conn.close()


def handlers(*fixtures):
    return {**default_handlers(fixture_backend(*fixtures)), **alerts.handlers(smtp_factory=FakeSMTP)}


def kinds(env):
    return [(r[0], r[1]) for r in env.conn.execute("SELECT kind, ref FROM owner_alert ORDER BY id")]


def test_an_unknown_debit_raises_an_alert_and_one_email_goes_to_the_owner(env):
    env.clock.advance(timedelta(days=3, hours=4))  # Thu 15 Oct 13:00
    deliver(env, "04-debit-city-electricity-balance-short.eml")
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    run_all(env, handlers("04-debit-city-electricity-balance-short.eml"))
    assert kinds(env) == [("unexpected_debit", "bank_txn:1")]
    ((host, port, msg),) = FakeSMTP.sent
    assert (host, port) == ("smtp.example.test", 587)
    assert (msg["From"], msg["To"], msg["Subject"]) == ("alerts@example.test", "owner@example.test",
                                                        "Cash-flow assistant: 1 thing needs you")
    body = msg.get_content()
    assert "- A ₹35,000 debit from HDFC Bank wasn't in the plan. What was it for?" in body
    assert "https://cash.example.test/attention" in body and msg.get_content_type() == "text/plain"
    assert env.conn.execute("SELECT COUNT(*) FROM owner_alert WHERE sent_at IS NULL").fetchone()[0] == 0


def test_a_returned_payment_tells_the_owner_the_bill_is_reopened(env):
    from tests.test_phase4_exit import DEBIT, RETURN, _plan_and_approve_paper, at, enqueue

    h = handlers(DEBIT, RETURN)
    _plan_and_approve_paper(env, h)
    at(env, 12, 12)
    deliver(env, DEBIT)
    enqueue(env, "poll_mail")
    run_all(env, h)
    at(env, 14, 11)
    deliver(env, RETURN)
    enqueue(env, "poll_mail")
    run_all(env, h)
    assert ("payment_failed", "payable:1") in kinds(env)
    assert any("The ₹1,80,000 payment to Ashirwad Paper Suppliers was returned. The bill is reopened and the plan updated."
               in m.get_content() for _, _, m in FakeSMTP.sent)


def test_a_matched_credit_says_money_received_with_the_new_lowest_balance(env):
    from app.domain.money import format_inr

    env.clock.advance(timedelta(days=1, hours=12))  # Tue 13 Oct, 21:00: after the alert's Date
    deliver(env, "02-credit-kaveri-traders.eml")
    queue.enqueue(env.conn, kind="monday_plan", payload={"business_id": 1}, clock=env.clock)
    queue.enqueue(env.conn, kind="poll_mail", payload={}, clock=env.clock)
    env.conn.commit()
    run_all(env, handlers("02-credit-kaveri-traders.eml"))
    ((kind, ref),) = [k for k in kinds(env) if k[0] == "money_received"]
    lowest = env.conn.execute("SELECT lowest_balance_paise FROM plan_run WHERE is_current = 1").fetchone()[0]
    assert alerts.alert_line(env.conn, kind, ref) == (
        f"₹33,000 received from Kaveri Traders. Lowest projected balance is now {format_inr(lowest)}. Plan updated.")


def test_a_drift_the_agent_cannot_explain_alerts_a_balance_mismatch(tmp_path):
    from app.ai.fixture_backend import FixtureBackend
    from tests.test_agent_scenarios import _drift
    from tests.web_helpers import make_web_env

    web_env, _ = make_web_env(tmp_path)
    web_env.handlers = default_handlers(FixtureBackend())
    _drift(web_env, missed_alert=False)
    ((ref,),) = web_env.conn.execute("SELECT ref FROM owner_alert WHERE kind = 'balance_mismatch'").fetchall()
    assert alerts.alert_line(web_env.conn, "balance_mismatch", ref) == (
        "HDFC Bank shows ₹5,65,000; I calculate ₹5,85,000. Difference ₹20,000. What is the actual balance?")
    web_env.conn.close()


def _raise(env, ref):
    alerts.raise_alert(env.conn, 1, "unexpected_debit", ref, clock=env.clock)
    env.conn.commit()


def _debit(env, rupees):
    from datetime import date

    from app.domain.models import BankTxnNew
    from app.ledger import writer

    txn = writer.create_bank_txn(
        BankTxnNew(account_id=1, direction="debit", amount_paise=rupees * 100, txn_date=date(2026, 10, 12),
                   counterparty="X", dedup_key=f"t:{rupees}", status="UNMATCHED"),
        actor="pipeline", reason="t", source_ref="t", conn=env.conn, clock=env.clock)
    return f"bank_txn:{txn.id}"


def test_alerts_inside_the_window_wait_and_go_as_one_digest(env):
    send = alerts.handlers(smtp_factory=FakeSMTP)
    _raise(env, _debit(env, 1000))
    run_all(env, send)
    assert len(FakeSMTP.sent) == 1
    env.clock.advance(timedelta(minutes=10))
    _raise(env, _debit(env, 2000))
    _raise(env, _debit(env, 3000))
    run_all(env, send)
    assert len(FakeSMTP.sent) == 1  # inside the 30-minute window: deferred
    env.clock.advance(timedelta(minutes=20))
    run_all(env, send)
    assert len(FakeSMTP.sent) == 2
    msg = FakeSMTP.sent[1][2]
    assert msg["Subject"] == "Cash-flow assistant: 2 things need you"
    assert "₹2,000" in msg.get_content() and "₹3,000" in msg.get_content() and "₹1,000" not in msg.get_content()


def test_with_no_smtp_host_nothing_is_sent_and_the_alerts_wait(env):
    env.settings = env.settings.model_copy(update={"smtp_host": ""})
    _raise(env, _debit(env, 1000))
    run_all(env, alerts.handlers(smtp_factory=FakeSMTP))
    assert FakeSMTP.sent == []
    assert env.conn.execute("SELECT COUNT(*) FROM owner_alert WHERE sent_at IS NULL").fetchone()[0] == 1
    assert env.conn.execute("SELECT status FROM job WHERE kind = 'send_alert'").fetchone()[0] == "done"


def test_a_payload_naming_a_recipient_is_refused(env):
    queue.enqueue(env.conn, kind="send_alert", payload={"business_id": 1, "to": "attacker@example.test"},
                  clock=env.clock)
    env.conn.commit()
    run_all(env, alerts.handlers(smtp_factory=FakeSMTP))
    assert env.conn.execute("SELECT status FROM job WHERE kind = 'send_alert'").fetchone()[0] == "dead"
    assert FakeSMTP.sent == []


def test_a_stored_name_cannot_add_lines_or_headers(env):
    env.conn.execute("UPDATE bank_account SET bank_name = ? WHERE id = 1",
                     ("HDFC\r\nBcc: attacker@example.test\r\n\r\nClick http://evil.example",))
    _raise(env, _debit(env, 1000))
    run_all(env, alerts.handlers(smtp_factory=FakeSMTP))
    msg = FakeSMTP.sent[0][2]
    assert msg["Bcc"] is None and sorted(msg.keys()) == sorted(
        ["From", "To", "Subject", "Content-Type", "Content-Transfer-Encoding", "MIME-Version"])
    alert_lines = [line for line in msg.get_content().splitlines() if line.startswith("- ")]
    assert len(alert_lines) == 1  # the name added no line
    assert alert_lines[0].startswith("- A ₹1,000 debit from HDFC Bcc: attacker@example.test Click")
    assert alert_lines[0].endswith(" wasn't in the plan. What was it for?")
    assert chr(13) not in msg.get_content()
    assert not any(line.startswith("Click") for line in msg.get_content().splitlines())
    assert templates.clean("x" * 100).endswith("…") and len(templates.clean("x" * 100)) == 60


def test_an_smtp_failure_is_retried_and_the_alerts_stay_unsent(env):
    FakeSMTP.fail = True
    _raise(env, _debit(env, 1000))
    run_all(env, alerts.handlers(smtp_factory=FakeSMTP))
    job = env.conn.execute("SELECT status, attempts FROM job WHERE kind = 'send_alert'").fetchone()
    assert (job[0], job[1]) == ("queued", 1)
    assert env.conn.execute("SELECT COUNT(*) FROM owner_alert WHERE sent_at IS NULL").fetchone()[0] == 1


def test_an_address_with_a_newline_is_refused():
    with pytest.raises(ValueError):
        smtp.message("alerts@example.test", "owner@example.test\r\nBcc: x@example.test", "s", "b")
