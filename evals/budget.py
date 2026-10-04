"""The live-mode budget guard (batch 7, CHG-010a, S5). A HARD limit in code:
one guard wraps the model backend for a whole invocation of the runner or the
ablation, and refuses any call that would go past either cap.

- **Calls:** at most 600 per invocation. A retried call (a 429) counts again,
  because it reached the API.
- **Cost:** at most 5,000,000 micro-USD ($5) per invocation, priced from each
  response's own token counts at config.yaml's rates. Before each call the
  guard adds the most expensive call so far to what is spent; if that would
  pass the cap, it stops instead of calling.
- **Pacing:** calls are sequential, with `delay_s` between them.
- **Rate limits:** a 429 waits 5, 10, 20, 40 and then 60 seconds and tries the
  same call again. One that outlasts all of that stops the invocation.
- **Spend cap and credits:** a refusal only the account's owner can lift stops
  the invocation at once, with no backoff: a permanent 429 (Google's spending
  cap or prepayment, CHG-040) or a 402 (the prepaid credits are used up,
  CHG-053).

Once stopped, every later call is refused as a permanent AIUnavailable and
`should_stop()` names the reason. The runner then ends the run as ERRORED,
starts no new run, and writes the partial report marked ABORTED."""

from __future__ import annotations

import argparse
import re
import time
from collections.abc import Callable
from typing import Any

from app.ai.client import AIUnavailable, Backend, RawAIResponse, cost_micro_usd, spend_cap
from app.config import AppConfig

MAX_CALLS = 600
MAX_MICRO_USD = 5_000_000
DELAY_S = 1.0
BACKOFF_S = (5, 10, 20, 40, 60)


def billing_refusal(e: AIUnavailable) -> str | None:
    """Why a refusal can't pass with time, or None: a 402 (the prepaid credits are used up, CHG-053), or a
    permanent 429 or other refusal in Google's spending-cap or prepayment words (CHG-040)."""
    if e.retryable:
        return None
    if e.code == 402:
        return "credits depleted: Google refused the call (402)"
    if e.code == 429 or spend_cap(e.detail or str(e), None):
        return f"spend cap: Google refused the call ({e.code})"
    return None


class BudgetGuard:
    def __init__(self, backend: Backend, app_config: AppConfig, *, max_calls: int = MAX_CALLS,
                 max_micro_usd: int = MAX_MICRO_USD, delay_s: float = DELAY_S,
                 backoff_s: tuple[float, ...] = BACKOFF_S, sleep: Callable[[float], None] = time.sleep) -> None:
        self.backend, self.app_config = backend, app_config
        self.max_calls, self.max_micro_usd = max_calls, max_micro_usd
        self.delay_s, self.backoff_s, self.sleep = delay_s, backoff_s, sleep
        self.calls = 0
        self.micro_usd = 0
        self.dearest_call = 0
        self.rate_limited = 0
        self.last_retries = 0  # the 429 retries made for the last call (the trace's `retries`, CHG-047)
        self.stopped: str | None = None

    def should_stop(self) -> str | None:
        return self.stopped

    def _stop(self, reason: str) -> AIUnavailable:
        self.stopped = self.stopped or reason
        return AIUnavailable(f"budget guard: {self.stopped}", retryable=False)

    def _check(self) -> None:
        if self.stopped:
            raise self._stop(self.stopped)
        if self.calls >= self.max_calls:
            raise self._stop(f"call cap reached: {self.calls} of {self.max_calls} calls used")
        if self.micro_usd + self.dearest_call > self.max_micro_usd:
            raise self._stop(f"cost cap reached: {self.micro_usd} micro-USD spent, and the next call could cost "
                             f"{self.dearest_call} (cap {self.max_micro_usd})")

    def generate(self, **kwargs: Any) -> RawAIResponse:
        self.last_retries = 0
        for attempt in range(len(self.backoff_s) + 1):
            self.last_retries = attempt
            self._check()
            if self.calls and self.delay_s:
                self.sleep(self.delay_s)
            self.calls += 1
            try:
                raw = self.backend.generate(**kwargs)
            except AIUnavailable as e:
                why = billing_refusal(e)
                if why:
                    raise self._stop(f"{why} and waiting can't help: {(e.detail or str(e))[:200]}") from None
                if e.code != 429:
                    raise
                self.rate_limited += 1
                if attempt == len(self.backoff_s):
                    raise self._stop(f"rate limited: a 429 outlasted {len(self.backoff_s)} backoffs") from None
                self.sleep(self.backoff_s[attempt])
                continue
            cost = cost_micro_usd(self.app_config, raw.input_tokens, raw.output_tokens + raw.thought_tokens)
            self.micro_usd += cost
            self.dearest_call = max(self.dearest_call, cost)
            return raw
        raise AssertionError("unreachable")

    def summary(self) -> dict[str, Any]:
        return {"calls": self.calls, "micro_usd": self.micro_usd, "rate_limited": self.rate_limited,
                "caps": {"calls": self.max_calls, "micro_usd": self.max_micro_usd}, "stopped": self.stopped}


def usd_cap(text: str) -> int:
    """`--max-usd` (CHG-041): dollars as text -> integer micro-USD, never a
    float. It can only lower the hard cap; anything else is refused."""
    m = re.fullmatch(r"\$?([0-9]+)(?:\.([0-9]{1,6}))?", text.strip())
    micro = int(m.group(1)) * 1_000_000 + int((m.group(2) or "").ljust(6, "0")) if m else 0
    if not 0 < micro <= MAX_MICRO_USD:
        raise argparse.ArgumentTypeError(f"--max-usd takes dollars above 0 and at most "
                                         f"{MAX_MICRO_USD / 1_000_000:.2f} (the hard cap), e.g. 1.50: {text!r}")
    return micro


def add_max_usd(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-usd", dest="max_micro_usd", type=usd_cap, default=MAX_MICRO_USD,
                   help=f"cost cap for this invocation in dollars (live only; at most "
                        f"{MAX_MICRO_USD / 1_000_000:.2f}, the default)")


def live_backend(app_config: AppConfig, *, confirmed: bool, max_micro_usd: int = MAX_MICRO_USD,
                 timeout_ms: int | None = None) -> BudgetGuard:
    """Gemini behind one guard for the whole invocation. Refuses to start
    without --yes-spend; reads GEMINI_API_KEY through Settings. `max_micro_usd`
    (from --max-usd) can only lower the hard cost cap. `timeout_ms` replaces
    config.yaml's request timeout for this invocation (the ablation's one
    timeout for every harness, CHG-044)."""
    if not 0 < max_micro_usd <= MAX_MICRO_USD:
        raise SystemExit(f"a cost cap must be above 0 and at most {MAX_MICRO_USD} micro-USD")
    if not confirmed:
        raise SystemExit(f"--ai live calls Gemini and is billed: at most {MAX_CALLS} calls and "
                         f"{MAX_MICRO_USD} micro-USD (${MAX_MICRO_USD / 1_000_000:.2f}) in this invocation. "
                         "Add --yes-spend to go ahead.")
    from app.ai.client import GeminiBackend
    from app.config import Settings

    settings = Settings()
    timeout_ms = timeout_ms or app_config.ai.timeout_ms
    guard = BudgetGuard(GeminiBackend(settings.gemini_api_key, timeout_ms=timeout_ms), app_config,
                        max_micro_usd=max_micro_usd)
    print(f"live: {app_config.model.id}; caps {MAX_CALLS} calls, {max_micro_usd} micro-USD; timeout {timeout_ms} ms; "
          f"{DELAY_S}s between calls", flush=True)
    return guard
