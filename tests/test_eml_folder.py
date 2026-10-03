"""The test inbox (batch 2 plan, CHG-004 step A6): EmlFolderSource lists by
sender and date, releases each email when the Clock reaches its Date, and
searches what has been released."""

import shutil
from datetime import date, datetime

import pytest

from app.clock import TIMEZONE, FakeClock
from app.ingest.eml_folder import EmlFolderSource, parse_message, sent_at
from app.ingest.mail_source import MessageRef
from tests.worker_helpers import ROOT

INBOX = ROOT / "fixtures" / "test_inbox"
BANK = "alerts@hdfcbank.example"


def at(day, hour=23, minute=59):
    return FakeClock(datetime(2026, 10, day, hour, minute, tzinfo=TIMEZONE))


def _names(refs):
    return [r.id for r in refs]


def test_emails_are_released_day_by_day_by_the_clock():
    assert _names(EmlFolderSource(INBOX, at(11)).list_new(date(2026, 10, 1), [BANK])) == []
    assert _names(EmlFolderSource(INBOX, at(12, 11, 42)).list_new(date(2026, 10, 1), [BANK])) == []
    assert _names(EmlFolderSource(INBOX, at(12, 11, 43)).list_new(date(2026, 10, 1), [BANK])) == [
        "01-debit-ashirwad-paper.eml",
    ]
    assert _names(EmlFolderSource(INBOX, at(14)).list_new(date(2026, 10, 1), [BANK])) == [
        "01-debit-ashirwad-paper.eml", "02-credit-kaveri-traders.eml", "03-return-ashirwad-paper.eml",
        "06-debit-ashirwad-paper-resent.eml", "10-statement-hdfc-locked.eml",
    ]


def test_only_the_given_senders_are_listed_whatever_their_case():
    source = EmlFolderSource(INBOX, at(31))
    assert source.list_new(date(2026, 10, 1), ["billing@vendor.example"]) == []
    assert len(source.list_new(date(2026, 10, 1), ["ALERTS@HDFCBANK.EXAMPLE"])) == 8  # 7 alerts, 1 statement
    assert len(source.list_new(date(2026, 10, 1), ["Accounts@AshirwadPaper.example"])) == 2  # invoices 08, 09


def test_since_is_a_day_in_kolkata():
    source = EmlFolderSource(INBOX, at(31))
    assert _names(source.list_new(date(2026, 10, 15), [BANK])) == [
        "04-debit-city-electricity-balance-short.eml", "05-offer-newsletter.eml", "07-credit-nandi-foods.eml",
    ]


@pytest.mark.parametrize("date_header", [None, "not a date", "Mon, 12 Oct 2026 11:42:07"])
def test_an_email_with_no_readable_date_is_listed_at_once(tmp_path, date_header):
    lines = [f"From: {BANK}", "Subject: x", "Message-ID: <x@hdfcbank.example>"]
    if date_header:
        lines.append(f"Date: {date_header}")
    (tmp_path / "x.eml").write_bytes(("\r\n".join(lines) + "\r\n\r\nbody\r\n").encode())
    refs = EmlFolderSource(tmp_path, at(1)).list_new(date(2026, 10, 1), [BANK])
    assert _names(refs) == ["x.eml"]
    assert sent_at(parse_message((tmp_path / "x.eml").read_bytes())) is None


def test_fetch_returns_the_bytes_as_stored():
    source = EmlFolderSource(INBOX, at(31))
    raw = source.fetch(MessageRef("01-debit-ashirwad-paper.eml"))
    assert raw.raw == (INBOX / "01-debit-ashirwad-paper.eml").read_bytes()
    assert raw.attachments == ()


@pytest.mark.parametrize("ref", ["../seed.py", r"..\seed.py", "README.md", "sub/x.eml"])
def test_fetch_refuses_anything_outside_the_inbox(ref):
    with pytest.raises(ValueError):
        EmlFolderSource(INBOX, at(31)).fetch(MessageRef(ref))


def test_search_matches_every_word_among_released_emails_newest_first():
    found = EmlFolderSource(INBOX, at(31)).search("ashirwad paper")
    assert _names(s.ref for s in found) == [
        "03-return-ashirwad-paper.eml", "09-invoice-ashirwad-new-bank.eml", "08-invoice-ashirwad-ap131.eml",
        "06-debit-ashirwad-paper-resent.eml", "01-debit-ashirwad-paper.eml",
    ]
    assert found[0].sender == BANK
    assert found[0].subject.startswith("NEFT transaction returned")
    assert EmlFolderSource(INBOX, at(12, 12)).search("returned") == []  # not released yet
    assert len(EmlFolderSource(INBOX, at(31)).search("hdfc", limit=2)) == 2


def test_every_fixture_says_it_is_fictional():
    for path in INBOX.glob("*.eml"):
        msg = parse_message(path.read_bytes())
        assert msg["X-Fixture-Note"].startswith("fictional data"), path.name
        assert msg["From"].addresses[0].domain.endswith(".example"), path.name


def test_an_attachment_is_returned_with_the_message(tmp_path):
    shutil.copy(INBOX / "01-debit-ashirwad-paper.eml", tmp_path / "a.eml")
    from email.message import EmailMessage

    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = BANK, "statement", "Fri, 16 Oct 2026 09:00:00 +0530"
    m.set_content("see attached")
    m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="stmt.pdf")
    (tmp_path / "b.eml").write_bytes(bytes(m))
    raw = EmlFolderSource(tmp_path, at(31)).fetch(MessageRef("b.eml"))
    assert [(a.filename, a.content_type, a.data) for a in raw.attachments] == [
        ("stmt.pdf", "application/pdf", b"%PDF-1.4 fake"),
    ]


def test_search_orders_by_time_across_utc_offsets(tmp_path):
    def mail(name, date_header):
        (tmp_path / name).write_bytes(
            f"From: {BANK}\r\nSubject: debit\r\nDate: {date_header}\r\n\r\nRs.1 debited\r\n".encode())

    mail("a.eml", "Mon, 12 Oct 2026 06:00:00 +0000")  # 11:30 IST, the later one
    mail("b.eml", "Mon, 12 Oct 2026 10:00:00 +0530")  # 10:00 IST
    found = EmlFolderSource(tmp_path, at(31)).search("debit")
    assert [s.ref.id for s in found] == ["a.eml", "b.eml"]


def test_search_understands_gmails_from_subject_after_and_before():
    """CHG-031: the live agent searched `from:alerts@hdfcbank.example 4821`, which matched nothing here
    though Gmail would have matched it (docs/evals/2026-10-04-live-after-batch-8)."""
    source = EmlFolderSource(INBOX, at(31))
    names = lambda q: _names(s.ref for s in source.search(q))  # noqa: E731
    assert names(f"from:{BANK} ashirwad paper") == [  # the bank's three, not Ashirwad's own invoices
        "03-return-ashirwad-paper.eml", "06-debit-ashirwad-paper-resent.eml", "01-debit-ashirwad-paper.eml"]
    assert all(s.sender == BANK for s in source.search(f"from:{BANK}"))
    assert names("subject:returned") == ["03-return-ashirwad-paper.eml"]
    assert names("ashirwad paper after:2026/10/14") == ["03-return-ashirwad-paper.eml",
                                                        "09-invoice-ashirwad-new-bank.eml"]
    assert names("ashirwad paper before:2026-10-13") == ["06-debit-ashirwad-paper-resent.eml",
                                                         "01-debit-ashirwad-paper.eml"]
    assert names("from:nobody@nowhere.example") == []
    assert names("after:someday") == []  # not a date: an ordinary word, found nowhere
