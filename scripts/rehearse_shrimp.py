"""The shrimp fortnight's rehearsal driver (CHG-058; dev only, R011). It plays
the demo's moves 1 to 6 (docs/demo-shrimp.md) through the real system, the
way evals/workflow.py plays the worked example's fortnights, and reuses its
harness without changing it: the real FastAPI app over HTTP (every action is a
form the page rendered), the real worker on its own connection, and the demo
clock the owner moves with the Settings page's form. Mail is
fixtures/shrimp_inbox itself, released as the clock passes each Date header,
as `make run-shrimp` reads it.

At each move it checks what the handoff's verification checklist asks:
item 4, that the move ends in the state the demo script says, and item 5,
that the two credits end MATCHED to their invoices (the balance with the
₹95,000 gap named in the event) with the plan's lowest balance at or above the
₹50,000 safety amount. On each explain_credit question it checks the agent's
finding is on the page, with nothing pre-selected.

    python scripts/rehearse_shrimp.py --ai fixtures            # offline: the canned replies, free
    python scripts/rehearse_shrimp.py --ai live --yes-spend --max-usd 1.00   # Gemini, under the budget guard

Live mode runs only when the PO authorises it. Each rehearsal writes its
report, its traces and its database to rehearsals/<date>T<time>-<mode>/
(git-ignored; never docs/evals)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.fernet import Fernet  # noqa: E402
from markupsafe import escape  # noqa: E402

from app.ai.client import Backend  # noqa: E402
from app.ai.fixture_backend import FIXTURES, FixtureBackend, load_replies  # noqa: E402
from app.clock import SystemClock, clock_for  # noqa: E402
from app.config import AppConfig, Settings, load_app_config  # noqa: E402
from app.db.connection import write_connection  # noqa: E402
from app.db.migrate import apply_migrations  # noqa: E402
from app.domain.money import format_inr, parse_inr  # noqa: E402
from app.jobs import alerts  # noqa: E402
from app.jobs.replan import replan  # noqa: E402
from app.main import create_app  # noqa: E402
from app.web import repo  # noqa: E402
from app.worker import default_handlers  # noqa: E402
from evals import budget, report  # noqa: E402
from evals.workflow import Browser, Run, Step, StepFailed, capturing_smtp  # noqa: E402
from evals.workflow_runs import approve, bill, calculated, confirm, plan, receivable  # noqa: E402
from fixtures import shrimp_seed  # noqa: E402
from fixtures.seed import BUSINESS_ID, DEV_HELPER_PASSWORD, DEV_OWNER_PASSWORD, HELPER_EMAIL, OWNER_EMAIL  # noqa: E402

START = "2026-10-19T09:00:00+05:30"  # .env.shrimp's DEMO_NOW
CONFIG = ROOT / "config.shrimp.yaml"
REPLIES = FIXTURES / "shrimp_ai_replies.json"
INBOX = FIXTURES / "shrimp_inbox"
UPLOADS = FIXTURES / "shrimp_uploads"
OUT = ROOT / "rehearsals"
SAFETY = parse_inr("50,000")
# The user's real voice note and photo go in fixtures/shrimp_uploads under these names (any extension the
# upload page takes); until then, and offline unless the store has their replies, the placeholders are used.
REAL = {"voice": "voice-note-lakshman", "photo": "repair-slip-photo"}
PLACEHOLDER = {"voice": "PLACEHOLDER-voice-note.wav", "photo": "PLACEHOLDER-repair-slip.png"}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
# What the caretaker's voice note and the repair slip say, as the owner reads them: typed into whatever the
# page marks (PO D28), as evals/workflow_runs.py does for the worked example's voice note.
REPAIR_SAID = {"party": "Sri Sai Motor Rewinding Works", "amount": "18,000", "due_date": "2026-10-25"}


@dataclass
class Move(Step):
    notes: list[str] = field(default_factory=list)  # what varied or was chosen; never a pass or a fail


class ShrimpRun(Run):
    """The shrimp fortnight's world: the evals harness's Run with the profile's seed, config, inbox and uploads
    in place of the worked example's (its __init__ builds that world, so it is not called)."""

    def __init__(self, folder: Path, backend: Backend, app_config: AppConfig, *, fixtures_mode: bool,
                 uploads: dict[str, Path]) -> None:
        self.tmp, self.fixtures_mode, self.uploads = folder, fixtures_mode, uploads
        db = folder / "shrimp.db"
        self.settings = Settings(
            _env_file=None, database_path=str(db), data_dir=str(folder / "files"), trace_dir=str(folder / "traces"),
            fernet_key=Fernet.generate_key().decode(), test_inbox_path=str(INBOX), mail_source="eml_folder",
            session_secret="shrimp-rehearsal", demo_now=START, demo_ai="fixtures" if fixtures_mode else "",
            app_config_path=str(CONFIG), fixture_replies_path=str(REPLIES) if fixtures_mode else "",
            smtp_host="smtp.capture.invalid", smtp_port=587, alert_from="alerts@payablesagent.example")
        self.app_config = app_config
        self.clock = clock_for(self.settings.demo_now, self.settings.data_dir)
        self.clock.reset()
        apply_migrations(db)
        self.conn = write_connection(db)
        try:
            shrimp_seed.seed(self.conn, self.clock)  # make reseed-shrimp
            replan(self.conn, BUSINESS_ID, triggered_by="seed", clock=self.clock)
            self.conn.commit()
            self.outbox: list = []
            self.handlers = {**default_handlers(backend), **alerts.handlers(smtp_factory=capturing_smtp(self.outbox))}
            app = create_app(self.settings, clock=self.clock, app_config=app_config)
            self.owner = Browser(app, "owner")
            self.owner.login(OWNER_EMAIL, DEV_OWNER_PASSWORD)
            self.helper = Browser(app, "helper")
            self.helper.login(HELPER_EMAIL, DEV_HELPER_PASSWORD)
        except BaseException:
            self.conn.close()
            raise
        self.steps: list[Step] = []
        self.should_stop = lambda: None

    def upload(self, which: str) -> int:
        """The helper uploads the voice note or the photo on the Add page; returns its source document."""
        path = self.uploads[which]
        self.helper.submit("/add", "/uploads", files={"file": (path.name, path.read_bytes(), MIME[path.suffix.lower()])})
        self.drain()
        return self.one("SELECT MAX(id) FROM source_document WHERE kind = ?", (which,))

    @contextmanager
    def step(self, actor: str, action: str) -> Iterator[Step]:
        s = Move(len(self.steps) + 1, f"{self.now():%a %d %b %H:%M}", actor, action)
        self.steps.append(s)
        try:
            yield s
        except StepFailed as e:
            s.error = str(e)
        except Exception as e:  # noqa: BLE001 - a crash fails the move, and the rehearsal goes on to report it
            s.error = f"{type(e).__name__}: {e}"
        finally:
            s.at = f"{self.now():%a %d %b %H:%M}"

    def note(self, text: str) -> None:
        self.steps[-1].notes.append(text)


# --- what the owner sees ---------------------------------------------------------------------------------


def credit(run: ShrimpRun, amount_paise: int) -> int:
    rows = run.rows("SELECT id FROM bank_txn WHERE direction = 'credit' AND amount_paise = ?", (amount_paise,))
    if len(rows) != 1:
        raise StepFailed(f"expected one credit of {format_inr(amount_paise)}, found {len(rows)}")
    return rows[0][0]


def credit_question(run: ShrimpRun, txn_id: int) -> int:
    qid = run.one("SELECT id FROM owner_question WHERE kind = 'explain_credit' AND status = 'OPEN' "
                  "AND json_extract(choices_json, '$.bank_txn_id') = ?", (txn_id,))
    if qid is None:
        raise StepFailed(f"no open explain_credit question for bank_txn {txn_id}")
    return qid


def card(page: str, action: str) -> str:
    """The Needs attention card (its <article>) holding the form for `action`."""
    found = [a for a in page.split("<article")[1:] if f'action="{action}"' in a]
    if len(found) != 1:
        raise StepFailed(f"the page shows {len(found)} cards for {action}")
    return found[0].split("</article>")[0]


def candidate_from(run: ShrimpRun, where: str, args: tuple = ()) -> int:
    cid = run.one("SELECT c.id FROM candidate c JOIN source_document d ON d.id = c.source_document_id "
                  f"WHERE c.status IN ('VALID', 'AWAITING_OWNER') AND {where} ORDER BY c.id", args)
    if cid is None:
        raise StepFailed(f"no entry waiting for the owner where {where} {args}")
    return cid


def finding_checks(run: ShrimpRun, qid: int, case_id: int) -> None:
    """The agent's finding is on the explain_credit card as its own words, and no invoice is pre-selected."""
    page = card(run.owner.get("/attention"), f"/questions/{qid}/answer")
    finding = repo.case_finding(run.conn, BUSINESS_ID, case_id)
    run.expect("agent-finding-shown", "The assistant found" in page, True,
               "PO: the explain_credit card shows what the agent found for its case, labelled as its words")
    run.expect("nothing-preselected", "checked" in page.split("<form", 1)[-1], False,
               "PO: the AI informs and the owner decides: no invoice is chosen for him")
    if finding:
        run.note(f"agent ({finding['outcome']}): {finding['summary']}")
        run.note("cited: " + ("; ".join(f"{m['sender']}: {m['subject']}" for m in finding["cited"]) or "nothing"))


def link_credit(run: ShrimpRun, qid: int, invoice: str, *, alias: bool) -> None:
    rid = run.one("SELECT id FROM receivable WHERE invoice_number = ?", (invoice,))
    run.owner.submit("/attention", f"/questions/{qid}/answer", pick={"receivable_id": str(rid)},
                     tick=("alias",) if alias else (), button="This paid the chosen invoice")
    run.drain()


def case_kind(run: ShrimpRun, txn_id: int) -> tuple[int, str]:
    row = run.one("SELECT id, kind FROM agent_case WHERE subject_ref = ?", (f"bank_txn:{txn_id}",))
    if row is None:
        raise StepFailed(f"no case for bank_txn {txn_id}")
    return row


# --- the fortnight ---------------------------------------------------------------------------------------


def fortnight(run: ShrimpRun) -> None:
    run.drain()

    with run.step("owner", "Start, Mon 19 Oct 09:00: the plan before the harvest"):
        p = plan(run)
        run.expect("balance", calculated(run), parse_inr("1,10,000"), "seed: ₹1,10,000 in HDFC **7310")
        run.expect("no-shortfall-yet", (p["valid"], p["lowest"]), (True, parse_inr("1,10,000")),
                   "the ₹2,00,000 advance (COMMITTED, Tue) covers the three bills; the lowest is today's ₹1,10,000")
        run.expect("balance-not-counted", receivable(run, "HARVEST-BAL"), "EXPECTED",
                   "seed: the ₹10,15,000 balance counts only when it lands or the owner asks for it early")
        run.note(f"plan: {p['lines']}")

    with run.step("vendor + owner", "Move 1, Mon 19 Oct 12:00: the last feed delivery's invoice; the owner confirms "
                                    "₹25,000"):
        run.move_to("2026-10-19T12:00")
        confirm(run, candidate_from(run, "d.kind = 'email' AND c.record_type = 'payable'"))
        run.expect("bill-in-the-ledger", run.one("SELECT amount_paise FROM payable WHERE party_id = 1"),
                   parse_inr("25,000"), "fixture 01: 10 bags x Rs.2,500.00 = Rs.25,000.00, to the dealer")
        run.expect("details-match-the-record", run.one("SELECT bank_status FROM party WHERE id = 1"), "verified",
                   "fixture 01's account ending 2201 is the one on record: nothing to ask")

    with run.step("bank + agent + owner", "Move 2, Tue 20 Oct 10:00: the advance from RAVI K's personal UPI; the "
                                          "owner links it to HARVEST-ADV"):
        run.move_to("2026-10-20T10:00")
        txn = credit(run, parse_inr("2,00,000"))
        case_id, kind = case_kind(run, txn)
        run.expect("payer-unknown", kind, "unknown_txn", "RAVI K (ravi.k@okaxis) names no party")
        qid = credit_question(run, txn)
        finding_checks(run, qid, case_id)
        link_credit(run, qid, "HARVEST-ADV", alias=True)
        rid = run.one("SELECT id FROM receivable WHERE invoice_number = 'HARVEST-ADV'")
        run.expect("checklist-5-advance-matched", run.one("SELECT status, party_id FROM bank_txn WHERE id = ?", (txn,)),
                   ("MATCHED", shrimp_seed.AGENT), "handoff checklist 5: the ₹2,00,000 credit is MATCHED to Ravi Traders")
        run.expect("checklist-5-advance-confirmed", receivable(run, "HARVEST-ADV"), "CONFIRMED",
                   "handoff checklist 5: HARVEST-ADV is CONFIRMED")
        run.expect("linked-to-this-credit", run.one("SELECT matched_txn_id FROM receivable WHERE id = ?", (rid,)), txn,
                   "the receivable names the credit that paid it")
        run.expect("balance", calculated(run), parse_inr("3,10,000"), "1,10,000 + 2,00,000; the alert shows "
                   "Rs.3,10,000.00")

    with run.step("vendor + owner", "Move 3, Wed 21 Oct 12:00: the ₹6,46,800 settlement with new bank details; the "
                                    "owner confirms the bill, rejects the details, and asks Ravi Traders to pay early"):
        run.move_to("2026-10-21T12:00")
        cand = candidate_from(run, "d.kind = 'email' AND c.record_type = 'payable'")
        run.expect("details-held", run.one("SELECT bank_status FROM party WHERE id = 1"), "change_pending",
                   "fixture 04's account 8876 differs from 2201 on record: code holds the old details and asks")
        confirm(run, cand)
        p = plan(run)
        run.expect("bill-in-the-ledger", run.one("SELECT amount_paise FROM payable WHERE invoice_number = "
                                                 "'SLAF/INV/1042'"), parse_inr("6,46,800"),
                   "fixture 04: Rs.5,32,800.00 + Rs.1,14,000.00")
        run.expect("shortfall", p["valid"], False, "₹3,10,000 cannot pay ₹6,46,800 + ₹25,000 on Mon 26 before the "
                   "₹10,15,000 balance is expected on Fri 30")
        early = run.rows("SELECT id, params_json, lowest_balance_paise, meets_rule FROM shortfall_option WHERE kind = "
                         "'early_receipt' AND plan_run_id = ?", (p["id"],))
        bal = run.one("SELECT id FROM receivable WHERE invoice_number = 'HARVEST-BAL'")
        early = [r for r in early if json.loads(r[1]).get("receivable_id") == bal]
        run.expect("ask-ravi-early-offered", len(early), 1, "the shortfall options include asking for HARVEST-BAL "
                   "early")
        run.note(f"plan: lowest {format_inr(p['lowest'])} on {p['lowest_on']}; {p['lines']}")
        if early:
            run.note(f"early-receipt option: {early[0][1]}, lowest {format_inr(early[0][2])}, meets the rule: "
                     f"{bool(early[0][3])}")
        run.owner.submit("/attention", "/parties/1/bank-change", button="Reject")
        run.drain()
        run.expect("old-details-kept", run.one("SELECT bank_account_mask, bank_ifsc, bank_status FROM party "
                                               "WHERE id = 1"), (*shrimp_seed.DEALER_BANK, "verified"),
                   "D5: the owner rejects 8876 (he checked by phone); 2201 stays on record")
        if early:
            run.owner.submit("/attention", f"/options/{early[0][0]}/choose")
            run.drain()
        run.expect("asked-not-counted", receivable(run, "HARVEST-BAL"), "EXPECTED",
                   "D13: asking a customer to pay early changes no ledger row; the money counts when it lands")

    with run.step("landowner + helper + owner", "Move 4, Thu 22 Oct 10:00: the lease asked early; the caretaker's "
                                                "voice note and photo of the ₹18,000 repair; the owner confirms "
                                                "one bill"):
        run.move_to("2026-10-22T10:00")
        lease = plan(run)["lines"].get("LEASE-OCT26")
        run.expect("lease-not-paid-early", (run.one("SELECT due_date FROM payable WHERE invoice_number = "
                                                    "'LEASE-OCT26'"), lease == "PAY 2026-10-22"),
                   ("2026-10-31", False), "the landowner's email changes no bill: the lease stays due Sat 31 Oct")
        run.note(f"lease: {lease}")
        voice_doc, photo_doc = run.upload("voice"), run.upload("photo")
        voice = candidate_from(run, "d.id = ?", (voice_doc,))
        transcript = run.one("SELECT transcript FROM candidate WHERE id = ?", (voice,)) or ""
        run.expect("transcript-beside-it", bool(transcript) and str(escape(transcript)) in run.owner.get("/attention"),
                   True, "the voice entry shows what was said beside the bill")
        run.note(f"transcript: {transcript}")
        confirm(run, voice, REPAIR_SAID)
        photo = candidate_from(run, "d.id = ?", (photo_doc,))
        run.owner.submit("/attention", f"/candidates/{photo}/reject")
        run.drain()
        run.expect("one-repair-bill", run.one("SELECT COUNT(*) FROM payable WHERE amount_paise = ?",
                                              (parse_inr("18,000"),)), 1,
                   "the voice note and the slip are one ₹18,000 bill: the owner confirms the voice note's and "
                   "rejects the photo's entry as the same bill")

    with run.step("bank + agent + owner", "Move 5, Fri 23 Oct 16:00: Ravi Traders pays the balance ₹95,000 short; "
                                          "the owner links it to HARVEST-BAL and approves Monday's payments"):
        run.move_to("2026-10-23T16:00")
        txn = credit(run, parse_inr("9,20,000"))
        case_id, kind = case_kind(run, txn)
        run.expect("payer-matches-amount-doesnt", kind, "ambiguous_match",
                   "RAVI TRADERS names Ravi Traders, but ₹9,20,000 is no open invoice's amount")
        qid = credit_question(run, txn)
        finding_checks(run, qid, case_id)
        link_credit(run, qid, "HARVEST-BAL", alias=False)
        run.expect("checklist-5-balance-confirmed", (receivable(run, "HARVEST-BAL"), run.one(
            "SELECT matched_txn_id FROM receivable WHERE invoice_number = 'HARVEST-BAL'")), ("CONFIRMED", txn),
                   "handoff checklist 5: HARVEST-BAL is CONFIRMED with the ₹9,20,000 credit")
        why = run.one("SELECT reason FROM event WHERE event_type = 'RECEIVABLE_CONFIRMED' ORDER BY id DESC LIMIT 1")
        run.expect("checklist-5-gap-named", "short by ₹95,000 (₹10,15,000 invoiced)" in (why or ""), True,
                   "handoff checklist 5: the event names the gap: 10,15,000 - 9,20,000 = 95,000")
        run.note(f"event: {why}")
        p = plan(run)
        run.expect("checklist-5-floor-holds", (p["valid"], p["lowest"] >= SAFETY), (True, True),
                   "handoff checklist 5: the plan's lowest balance is at or above the ₹50,000 safety amount")
        run.note(f"plan: lowest {format_inr(p['lowest'])} on {p['lowest_on']}; {p['lines']}")
        approve(run)
        run.expect("dealer-approved", bill(run, "SLAF/INV/1042"), "PAYMENT_EXPECTED",
                   "the owner approves Monday's payments, the dealer's settlement among them")

    with run.step("bank", "Move 6, Mon 26 Oct 11:00: the dealer's NEFT lands; the bill is paid"):
        run.move_to("2026-10-26T11:00")
        run.expect("dealer-paid", bill(run, "SLAF/INV/1042"), "PAID",
                   "fixture 08's ₹6,46,800 NEFT to SRI LAKSHMI AQUA FEEDS matches the approved bill")
        run.expect("balance", calculated(run), parse_inr("5,83,200"), "12,30,000 - 6,46,800; the alert shows "
                   "Rs.5,83,200.00")


# --- running and reporting -------------------------------------------------------------------------------


def uploads_for(live: bool) -> tuple[dict[str, Path], list[str]]:
    """The voice note and photo to upload: the user's real files when they are in place (offline only once the
    store has their replies), else the placeholders."""
    canned = load_replies("shrimp_uploads", REPLIES)
    chosen, said = {}, []
    for which in ("voice", "photo"):
        real = sorted(p for p in UPLOADS.glob(f"{REAL[which]}.*") if p.suffix.lower() in MIME)
        use = real[0] if len(real) == 1 and (live or real[0].name in canned) else UPLOADS / PLACEHOLDER[which]
        chosen[which] = use
        said.append(f"{which}: {use.name}")
    return chosen, said


def markdown(steps: list[Move], meta: dict[str, Any]) -> str:
    ok = all(s.ok for s in steps)
    out = [f"# Shrimp rehearsal, {meta['mode']}: {'PASS' if ok else 'FAIL'}", "",
           *(f"- {k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}" for k, v in meta.items()),
           ""]
    for s in steps:
        out += [f"## {s.n}. {s.action}: {'PASS' if s.ok else 'FAIL'}", "", f"{s.actor}, read at {s.at}", ""]
        if s.error:
            out += [f"**Error:** {s.error}", ""]
        if s.checks:
            out += ["| Check | Expected | Actual | Result | Why |", "| --- | --- | --- | --- | --- |"]
            out += [f"| `{c.id}` | {c.expected} | {c.actual} | {'PASS' if c.ok else '**FAIL**'} | {c.why} |"
                    for c in s.checks]
            out.append("")
        out += [f"- {n}" for n in s.notes] + ([""] if s.notes else [])
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python scripts/rehearse_shrimp.py", description="Rehearse the shrimp demo.")
    p.add_argument("--ai", choices=["fixtures", "live"], required=True)
    p.add_argument("--yes-spend", action="store_true", help="required with --ai live")
    p.add_argument("--out", type=Path, default=OUT)
    budget.add_max_usd(p)
    args = p.parse_args(argv)
    config = load_app_config(CONFIG)
    live = args.ai == "live"
    guard = budget.live_backend(config, confirmed=args.yes_spend, max_micro_usd=args.max_micro_usd) if live else None
    backend = guard if guard is not None else FixtureBackend(REPLIES)
    uploads, said = uploads_for(live)
    stamp = SystemClock().now()
    folder = args.out / f"{stamp:%Y-%m-%dT%H%M%S}-{args.ai}"
    folder.mkdir(parents=True)
    run = ShrimpRun(folder, backend, config, fixtures_mode=not live, uploads=uploads)
    if guard is not None:
        run.should_stop = guard.should_stop
    try:
        fortnight(run)
    except Exception as e:  # noqa: BLE001 - outside every move (the opening drain): reported as its own move
        run.steps.append(Move(len(run.steps) + 1, f"{run.now():%a %d %b %H:%M}", "worker", "(outside any move)",
                              error=f"{type(e).__name__}: {e}"))
    finally:
        run.close()
    meta = {"mode": args.ai, "model": "fixture-ai" if not live else config.model.id,
            "prompt_version": config.prompts.version, "commit": report.git_commit(),
            "date": stamp.isoformat(timespec="seconds"), "uploads": said,
            "budget": guard.summary() if guard else None}
    (folder / "report.md").write_text(markdown(run.steps, meta), encoding="utf-8", newline="\n")
    data = {"meta": meta, "ok": all(s.ok for s in run.steps), "moves": [
        {"n": s.n, "at": s.at, "actor": s.actor, "action": s.action, "ok": s.ok, "error": s.error, "notes": s.notes,
         "checks": [{"id": c.id, "expected": c.expected, "actual": c.actual, "ok": c.ok, "why": c.why}
                    for c in s.checks]} for s in run.steps]}
    (folder / "report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
                                        encoding="utf-8", newline="\n")
    for s in run.steps:
        print(f"{'PASS' if s.ok else 'FAIL'}  {s.action}" + (f"  [{s.error}]" if s.error else ""))
    if guard is not None:
        print(f"budget: {guard.summary()}")
    print(f"report: {folder / 'report.md'}")
    return 0 if data["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
