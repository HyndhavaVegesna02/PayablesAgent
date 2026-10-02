"""`make smoke-gemini`: the one live check that the prompts and schemas work
on Gemini itself. It costs money, so `make test` and every default path leave
it alone, and it refuses to run without --yes-call-gemini. It makes at most
MAX_CALLS (3) calls: sort and extract for the test inbox's debit alert, and
extract for its return notice, and checks each reply. Run it only when the
PO has authorised a live run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.ai.client import Backend, GeminiBackend
from app.ai.email_text import email_text_from_bytes
from app.ai.extract import extract_document
from app.ai.sort import sort_document
from app.clock import SystemClock
from app.config import AppConfig, Settings, load_app_config
from app.domain.money import parse_inr
from app.trace.tracer import Tracer

MAX_CALLS = 3
INBOX = Path(__file__).resolve().parents[2] / "fixtures" / "test_inbox"
DEBIT = "01-debit-ashirwad-paper.eml"
RETURN = "03-return-ashirwad-paper.eml"


class CallBudget:
    """Wraps a Backend and refuses any call past MAX_CALLS."""

    def __init__(self, inner: Backend) -> None:
        self.inner, self.calls = inner, 0

    def generate(self, **kw):
        if self.calls >= MAX_CALLS:
            raise RuntimeError(f"smoke-gemini makes at most {MAX_CALLS} calls")
        self.calls += 1
        return self.inner.generate(**kw)


def _text(name: str) -> str:
    return email_text_from_bytes((INBOX / name).read_bytes())


def _amount(text: str) -> int | None:
    try:
        return parse_inr(text)
    except ValueError:
        return None


def run(backend: Backend, app_config: AppConfig, tracer: Tracer) -> list[str]:
    """Returns the problems found; an empty list means the smoke run passed."""
    budget = CallBudget(backend)
    kw = dict(backend=budget, app_config=app_config, tracer=tracer)
    problems: list[str] = []

    sort = sort_document(_text(DEBIT), input_ref=f"fixture:{DEBIT}", **kw)
    if sort.parsed is None or sort.parsed.doc_type != "bank_alert":
        problems.append(f"sort: expected bank_alert, got {sort.parsed or sort.schema_error}")

    alert = extract_document("bank_alert", _text(DEBIT), thinking=app_config.model.thinking.extract,
                             input_ref=f"fixture:{DEBIT}", **kw)
    if alert.parsed is None:
        problems.append(f"extract bank_alert: {alert.schema_error}")
    elif (alert.parsed.account_last4, alert.parsed.direction, _amount(alert.parsed.amount_text)) != (
        "4821", "debit", 18_000_000,
    ):
        problems.append(f"extract bank_alert: unexpected {alert.parsed.model_dump(mode='json')}")

    notice = extract_document("failure_notice", _text(RETURN), thinking=app_config.model.thinking.extract,
                              input_ref=f"fixture:{RETURN}", **kw)
    if notice.parsed is None:
        problems.append(f"extract failure_notice: {notice.schema_error}")
    elif "".join((notice.parsed.original_reference or "").split()).upper() != "N286261234567":
        problems.append(f"extract failure_notice: unexpected {notice.parsed.model_dump(mode='json')}")

    cost = sort.cost_micro_usd + alert.cost_micro_usd + notice.cost_micro_usd
    print(f"smoke-gemini: {budget.calls} calls, {cost} micro-USD; trace run {tracer.run_id}")
    for p in problems:
        print(f"smoke-gemini: FAILED {p}", file=sys.stderr)
    if not problems:
        print("smoke-gemini: passed")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live, billed check of the Gemini prompts (at most 3 calls).")
    parser.add_argument("--yes-call-gemini", action="store_true", help="confirm a live, billed run")
    args = parser.parse_args(argv)
    if not args.yes_call_gemini:
        print("smoke-gemini makes live, billed Gemini calls; pass --yes-call-gemini to run it",
              file=sys.stderr)
        return 2
    settings, app_config, clock = Settings(), load_app_config(), SystemClock()
    try:
        backend = GeminiBackend(settings.gemini_api_key, timeout_ms=app_config.ai.timeout_ms)
    except ValueError as e:
        print(f"smoke-gemini: {e}", file=sys.stderr)
        return 2
    tracer = Tracer(f"smoke-gemini-{clock.now():%Y%m%dT%H%M%S}", settings.trace_dir, clock)
    return 1 if run(backend, app_config, tracer) else 0


if __name__ == "__main__":
    sys.exit(main())
