"""Makes the bank alerts the full-workflow runs need beyond the existing
fixtures (batch 7, CHG-027): fixtures/agent_inbox/2x-*.eml and 3x-*.eml, plus
their canned replies under `agent_inbox` in fixtures/ai_replies.json, the one
replies store. Every value is fictional, and the layout is fixture 01's (HDFC
InstaAlerts).

Each alert's available balance is the account's balance after that debit or
credit in its own run. Run A follows the TDD's golden table (Part 1, "Worked
example"): ₹6,20,000 on Mon 12 Oct, then each payment the plan makes. Run B's
are worked out in each alert's note below, from the statement's closing balance.
So the drift check sees a gap only where the run means one: in run B, the
₹25,000 debit whose alert arrives late.

    uv run python scripts/make_workflow_fixtures.py

Running it again rewrites the same files and replies."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "fixtures" / "agent_inbox"
REPLIES = ROOT / "fixtures" / "ai_replies.json"

# file, Date header, direction, amount, counterparty, reference, available balance (None: not shown), why
ALERTS = [
    # Run A: the worked example's payments, each available balance from the golden table
    ("20-debit-pf-esi-45000.eml", "Thu, 15 Oct 2026 10:05:11 +0530", "debit", "45,000", "EPFO ESIC CHALLAN",
     "N289261000451", "4,28,000",
     "Run A: PF and ESI paid on Thu 15 Oct; 4,73,000 - 45,000"),
    ("21-debit-city-electricity-35000.eml", "Thu, 15 Oct 2026 10:20:43 +0530", "debit", "35,000",
     "CITY ELECTRICITY BOARD", "BP2610150098812", "3,93,000",
     "Run A: electricity paid on Thu 15 Oct; the golden table's 3,93,000"),
    ("22-debit-gst-90000.eml", "Mon, 19 Oct 2026 10:10:05 +0530", "debit", "90,000", "NETBANKING TAX PAYMENT",
     "N293261000902", "5,03,000",
     "Run A: GST paid on Mon 19 Oct; the golden table's 5,03,000 (Nandi paid on Fri 16). Its description names "
     "no tax office (no statutory payee word, CHG-028), so the owner links it"),
    ("23-debit-prime-chem-120000.eml", "Thu, 22 Oct 2026 10:15:27 +0530", "debit", "1,20,000",
     "PRIME CHEM INDUSTRIES", "N296261001203", "3,83,000",
     "Run A: Prime Chem paid on Thu 22 Oct; the golden table's 3,83,000"),
    ("24-debit-shree-ganesh-12390.eml", "Thu, 22 Oct 2026 10:31:02 +0530", "debit", "12,390",
     "SHREE GANESH HARDWARE", "628796103124", "3,70,610",
     "Run A: Shree Ganesh's bill 418 (the handwritten one) paid on Thu 22 Oct; 3,83,000 - 12,390"),
    # Run B: the bad fortnight. The account after the statement (12-13 Oct) and the paper
    # payment's return: 4,72,410 + 1,80,000 = 6,52,410 in the ledger.
    ("30-debit-shree-transport-25000-delayed.eml", "Wed, 14 Oct 2026 09:30:18 +0530", "debit", "25,000",
     "SHREE TRANSPORT", "628714093018", "4,47,410",
     "Run B: a UPI debit on Wed 14 Oct whose alert reached the mailbox two days late, after the mail check's "
     "window had passed its date (4,72,410 - 25,000, before the paper payment came back at 10:21)"),
    ("31-debit-ashirwad-paper-15000.eml", "Wed, 14 Oct 2026 12:15:40 +0530", "debit", "15,000", "ASHIRWAD PAPER",
     "628714121540", None,
     "Run B: a UPI debit no bill explains, next to the hidden-instruction email (12); this alert shows no balance"),
    ("32-debit-ramesh-k-12500.eml", "Wed, 14 Oct 2026 15:02:09 +0530", "debit", "12,500", "RAMESH K",
     "628714150209", None,
     "Run B: a UPI debit no bill or email explains; the agent asks the owner. This alert shows no balance"),
    ("33-debit-ashirwad-paper-180000.eml", "Fri, 16 Oct 2026 10:00:31 +0530", "debit", "1,80,000",
     "ASHIRWAD PAPER SUPPLIERS", "N290261180001", "4,19,910",
     "Run B: PAPER-001 paid again after Wednesday's return. The bank's balance includes the delayed "
     "25,000 debit the ledger lacks: 6,52,410 - 25,000 - 15,000 - 12,500 - 1,80,000"),
    ("34-debit-pf-esi-45000-runb.eml", "Fri, 16 Oct 2026 10:10:12 +0530", "debit", "45,000", "EPFO ESIC CHALLAN",
     "N290261045002", "3,74,910", "Run B: PF and ESI paid on Fri 16 Oct; 4,19,910 - 45,000"),
    ("35-debit-city-electricity-35000-runb.eml", "Fri, 16 Oct 2026 10:20:55 +0530", "debit", "35,000",
     "CITY ELECTRICITY BOARD", "BP2610160099120", "3,39,910",
     "Run B: electricity paid on Fri 16 Oct; 3,74,910 - 35,000"),
    ("36-debit-gst-90000-runb.eml", "Mon, 19 Oct 2026 10:12:44 +0530", "debit", "90,000", "GST CHALLAN CBIC",
     "N293261090003", "2,49,910",
     "Run B: GST paid on Mon 19 Oct; 3,39,910 (the drift settled: the bank's and the ledger's) - 90,000"),
    ("37-debit-prime-chem-53000.eml", "Thu, 22 Oct 2026 10:16:08 +0530", "debit", "53,000", "PRIME CHEM INDUSTRIES",
     "N296261053004", "1,96,910",
     "Run B: the first part of the split Prime Chem bill, paid on Thu 22 Oct; 2,49,910 - 53,000"),
]

# Run B's drift case (a 25,000 gap) gets its own script; the eval suite's 20,000 one is untouched.
DRIFT_B = {
    "name": "workflow run B: delayed alert recovered from mail",
    "case": "Explain the ₹25,000 gap in account",
    "rules": [
        {"if": [": VALID, every rule check passed"], "step": {
            "notes": "the delayed alert explains the gap",
            "final": {"outcome": "RESOLVED",
                      "summary": "The gap is a ₹25,000 UPI debit to SHREE TRANSPORT on Wed 14 Oct. Its alert "
                                 "email arrived late and the mail check never read it; it is in the ledger now.",
                      "cited_message_ids": ["30-debit-shree-transport-25000-delayed.eml"],
                      "relied_on_candidate_ids": "$valid_candidates"}}},
        {"if": ["message 30-debit-shree-transport-25000-delayed.eml"], "unless": ["add_candidate("], "step": {
            "notes": "an alert the mail check did not read",
            "tool": {"name": "add_candidate", "args": {
                "record_type": "bank_alert", "message_id": "30-debit-shree-transport-25000-delayed.eml",
                "fields": {"account_last4": "4821", "direction": "debit", "amount_text": "Rs.25,000.00",
                           "txn_date": "2026-10-14", "counterparty": "SHREE TRANSPORT",
                           "reference": "628714093018", "available_balance_text": "Rs.4,47,410.00",
                           "uncertain_fields": []}}}}},
        {"step": {"notes": "look for a debit alert for the gap",
                  "tool": {"name": "search_gmail", "args": {"query": "debited 4821 25,000"}}}},
    ],
}


def _rupees(text: str) -> str:
    return f"Rs.{text}.00"


def eml(name: str, date: str, direction: str, amount: str, party: str, ref: str, balance: str | None,
        why: str) -> str:
    verb, prep = ("debited from", "to") if direction == "debit" else ("credited to", "from")
    stamp = name.split("-")[0]
    lines = [
        f"X-Fixture-Note: fictional data; format modelled on HDFC InstaAlerts. {why}",
        "From: HDFC Bank InstaAlerts <alerts@hdfcbank.example>",
        "To: owner@example.test",
        f"Subject: {direction.capitalize()} alert: {_rupees(amount)} {verb} your account ending 4821",
        f"Date: {date}",
        f"Message-ID: <instaalert-workflow-{stamp}-4821@hdfcbank.example>",
        "MIME-Version: 1.0",
        'Content-Type: text/plain; charset="utf-8"',
        "",
        "Dear Customer,",
        "",
        f"{_rupees(amount)} has been {verb} account **4821 towards NEFT {prep} {party} on "
        f"{_day(date)}.",
        "",
        f"Reference Number: {ref}",
    ]
    if balance is not None:
        lines.append(f"Available balance: {_rupees(balance)}")
    lines += ["", "If you did not authorise this transaction, please call us immediately.", "", "Warm Regards,",
              "HDFC Bank", "(This is a fictional fixture. No real bank, account or person is described.)", ""]
    return "\n".join(lines)


def _day(date: str) -> str:
    from email.utils import parsedate_to_datetime

    return f"{parsedate_to_datetime(date):%d-%m-%y}"


def _iso(date: str) -> str:
    from email.utils import parsedate_to_datetime

    return parsedate_to_datetime(date).date().isoformat()


def reply(date: str, direction: str, amount: str, party: str, ref: str, balance: str | None) -> dict:
    return {
        "SortResult": {"doc_type": "bank_alert", "reason": "A bank alert for a debit or credit."},
        "BankAlertExtract": {
            "account_last4": "4821", "direction": direction, "amount_text": _rupees(amount),
            "txn_date": _iso(date), "counterparty": party, "reference": ref,
            "available_balance_text": None if balance is None else _rupees(balance), "uncertain_fields": [],
        },
    }


def main() -> None:
    replies = json.loads(REPLIES.read_text(encoding="utf-8"))
    for name, date, direction, amount, party, ref, balance, why in ALERTS:
        (INBOX / name).write_text(eml(name, date, direction, amount, party, ref, balance, why), encoding="utf-8",
                                  newline="\n")
        replies["agent_inbox"][name] = reply(date, direction, amount, party, ref, balance)
    replies["agent_scripts"] = [x for x in replies["agent_scripts"] if x["name"] != DRIFT_B["name"]] + [DRIFT_B]
    REPLIES.write_text(json.dumps(replies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(ALERTS)} alerts to {INBOX.relative_to(ROOT)}, their replies, and run B's drift script")


if __name__ == "__main__":
    main()
