"""The one function that calls Gemini (TDD Part 2, "At a glance": "The AI sits
behind one function"). This is the only module that imports google.genai
(tests/test_ai_boundary.py fails otherwise).

call() sends one request through a Backend and returns the text, our own
parse of it against a Pydantic schema, the token counts and the cost. Every
call writes one trace step. Tests use a fake Backend (tests/fake_ai.py); the
real GeminiBackend is built only by the worker and `make smoke-gemini`, from
Settings, and never by a test.

Request shape (verified offline against google-genai 2.27.0):
- the thinking level is checked here, against low/medium/high. The SDK also
  accepts "minimal", which Gemini 3.8 Flash does not support (TDD Part 1);
- structured output is response_mime_type="application/json" plus
  response_json_schema from the Pydantic model, and we parse r.text ourselves;
- no temperature, top_p, top_k or thinking_budget is ever sent;
- the SDK's own retries stay off, so one call is one attempt and the job queue
  owns retry and backoff;
- a photo, PDF or voice note goes as a Part (its bytes and mime type), which
  becomes an inline_data part; the trace records only its mime type, size and
  sha256, never its bytes (batch 5 plan, S2)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import AppConfig
from app.trace.tracer import Tracer

THINKING_LEVELS = frozenset({"low", "medium", "high"})
RESULT_PREVIEW_CHARS = 200


class AIUnavailable(Exception):
    """Gemini did not answer. `retryable` says whether the job queue should
    try again later (server error, rate limit, timeout) or give up. `detail`
    is the reason Google gave (e.g. "API key not valid" or "API not enabled"),
    already redacted, so it is safe in job.last_error and the trace."""

    def __init__(self, message: str, *, retryable: bool, code: int | None = None,
                 status: str | None = None, detail: str | None = None) -> None:
        super().__init__(f"{message}: {detail}" if detail else message)
        self.retryable = retryable
        self.code = code
        self.status = status
        self.detail = detail


REDACTED_KEY = "***REDACTED-KEY***"
_GOOGLE_API_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")


def redact_key(text: str, key: str | None = None) -> str:
    """Removes the API key from an error message: the literal key we sent, and
    anything shaped like a Google API key, in case the server echoes one."""
    if key:
        text = text.replace(key, REDACTED_KEY)
    return _GOOGLE_API_KEY.sub(REDACTED_KEY, text)


@dataclass(frozen=True)
class RawAIResponse:
    text: str | None
    input_tokens: int
    output_tokens: int  # candidates only
    thought_tokens: int


@dataclass(frozen=True)
class Part:
    """A file sent to the model: a photo, a PDF or a voice note."""

    mime_type: str
    data: bytes = field(repr=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


# What the model is shown: text alone, or text and files in order.
Contents = str | Sequence[str | Part]


def describe(contents: Contents) -> list[dict[str, Any]]:
    """The trace's record of what was sent: text by length, a file by its mime
    type, size and sha256. Never the file's bytes."""
    items = [contents] if isinstance(contents, str) else list(contents)
    return [{"text_chars": len(c)} if isinstance(c, str)
            else {"mime_type": c.mime_type, "bytes": len(c.data), "sha256": c.sha256} for c in items]


class Backend(Protocol):
    def generate(self, *, model: str, system: str, contents: Contents, thinking: str,
                 json_schema: dict[str, Any] | None) -> RawAIResponse: ...


@dataclass(frozen=True)
class AIResult:
    text: str | None
    parsed: BaseModel | None
    schema_error: str | None  # why `text` did not match the schema, when it did not
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    cost_micro_usd: int


def cost_micro_usd(app_config: AppConfig, input_tokens: int, billed_output_tokens: int) -> int:
    p = app_config.model.pricing
    total = input_tokens * p.input_micro_usd_per_mtok + billed_output_tokens * p.output_micro_usd_per_mtok
    return -(-total // 1_000_000)  # integer ceiling: a cost is never rounded down to free


def call(
    *,
    job: str,
    thinking: str,
    system: str,
    context: Contents,
    schema: type[BaseModel] | None,
    backend: Backend,
    app_config: AppConfig,
    tracer: Tracer,
    input_ref: str,
    prompt_version: str | None = None,
) -> AIResult:
    if thinking not in THINKING_LEVELS:
        raise ValueError(f"thinking level must be one of {sorted(THINKING_LEVELS)}, got {thinking!r}")
    try:
        raw = backend.generate(
            model=app_config.model.id, system=system, contents=context, thinking=thinking,
            json_schema=schema.model_json_schema() if schema is not None else None,
        )
    except AIUnavailable as e:
        kind = "retryable" if e.retryable else "permanent"
        tracer.step(input_ref=input_ref, model=app_config.model.id, thinking=thinking, tool=f"ai.call:{job}",
                    result=None, validation=f"not run: AI unavailable ({kind}, {e.code}): {e}", retries=0)
        raise
    parsed, schema_error = None, None
    if schema is not None:
        try:
            parsed = schema.model_validate_json(raw.text or "")
        except ValidationError as e:
            schema_error = _short(e)
    billed_output = raw.output_tokens + raw.thought_tokens
    cost = cost_micro_usd(app_config, raw.input_tokens, billed_output)
    tracer.step(
        input_ref=input_ref,
        model=app_config.model.id,
        thinking=thinking,
        tool=f"ai.call:{job}",
        arguments={"prompt_version": prompt_version, "schema": schema.__name__ if schema else None,
                   **({} if isinstance(context, str) else {"contents": describe(context)})},
        result=None if raw.text is None else raw.text[:RESULT_PREVIEW_CHARS],
        validation="schema: passed" if schema_error is None else f"schema: failed: {schema_error}",
        retries=0,
        escalation_rule=None,
        tokens={"input": raw.input_tokens, "output": raw.output_tokens, "thoughts": raw.thought_tokens},
        cost_micro_usd=cost,
    )
    return AIResult(raw.text, parsed, schema_error, raw.input_tokens, raw.output_tokens,
                    raw.thought_tokens, cost)


def _short(e: ValidationError) -> str:
    errs = e.errors()
    first = errs[0] if errs else {"loc": (), "msg": str(e)}
    where = ".".join(str(x) for x in first.get("loc", ())) or "(root)"
    more = f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""
    return f"{where}: {first.get('msg')}{more}"


# --- the real backend -------------------------------------------------------------


# A 429 can mean two things (CHG-040). A rate limit passes with time; a spending cap or empty prepayment
# doesn't, until the Google project's owner acts. Only the words Google uses for the second, or the reason
# it files it under, make a 429 permanent.
_SPEND_CAP_WORDS = ("spending cap", "spend cap", "prepayment")
_SPEND_CAP_REASONS = ("SPEND", "BILLING", "PREPAY")


def spend_cap(message: object, details: object) -> bool:
    """Whether a 429 is a spending cap, billing or prepayment refusal."""
    if any(w in str(message or "").lower() for w in _SPEND_CAP_WORDS):
        return True
    error = details.get("error", details) if isinstance(details, dict) else {}
    infos = error.get("details", []) if isinstance(error, dict) else []
    return any(isinstance(i, dict) and str(i.get("@type", "")).endswith("ErrorInfo")
               and any(r in str(i.get("reason", "")).upper() for r in _SPEND_CAP_REASONS) for i in infos)


class GeminiBackend:
    """google-genai behind the Backend protocol. Errors become AIUnavailable:
    server errors, 429 and network timeouts are retryable; any other 4xx is
    not (retrying a refused request cannot help), nor is a 429 for a spending
    cap (CHG-040)."""

    def __init__(self, api_key: str, *, timeout_ms: int, httpx_client: httpx.Client | None = None) -> None:
        if not api_key.strip():
            raise ValueError("GEMINI_API_KEY is not set")
        from google import genai
        from google.genai import types

        self._types = types
        self._key = api_key  # kept only to redact it from error messages
        options = types.HttpOptions(timeout=timeout_ms, httpx_client=httpx_client)
        self._client = genai.Client(api_key=api_key, http_options=options)

    def _detail(self, message: object) -> str | None:
        text = str(message or "").strip()
        return redact_key(text, self._key)[:500] or None

    def generate(self, *, model: str, system: str, contents: Contents, thinking: str,
                 json_schema: dict[str, Any] | None) -> RawAIResponse:
        from google.genai import errors

        t = self._types
        if not isinstance(contents, str):  # one user turn: text and inline files, in order
            contents = [c if isinstance(c, str) else t.Part.from_bytes(data=c.data, mime_type=c.mime_type)
                        for c in contents]
        config = t.GenerateContentConfig(
            system_instruction=system,
            thinking_config=t.ThinkingConfig(thinking_level=thinking),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            **({"response_mime_type": "application/json", "response_json_schema": json_schema}
               if json_schema is not None else {}),
        )
        try:
            r = self._client.models.generate_content(model=model, contents=contents, config=config)
        # `from None`: the SDK's own exception carries the unredacted message, so it
        # is not chained into tracebacks; the redacted detail says the same thing.
        except errors.ServerError as e:
            raise AIUnavailable(f"Gemini server error {e.code}", retryable=True, code=e.code,
                                status=e.status, detail=self._detail(e.message)) from None
        except errors.APIError as e:
            retryable = e.code is None or (e.code == 429 and not spend_cap(e.message, e.details))
            raise AIUnavailable(f"Gemini refused the request: {e.code} {e.status}", retryable=retryable,
                                code=e.code, status=e.status, detail=self._detail(e.message)) from None
        except httpx.TransportError as e:  # timeouts and connection errors are not APIError
            raise AIUnavailable(f"Gemini unreachable: {type(e).__name__}", retryable=True,
                                detail=self._detail(str(e))) from None
        u = r.usage_metadata
        return RawAIResponse(
            text=r.text,
            input_tokens=(u.prompt_token_count or 0) if u else 0,
            output_tokens=(u.candidates_token_count or 0) if u else 0,
            thought_tokens=(u.thoughts_token_count or 0) if u else 0,
        )


# --- prompts ----------------------------------------------------------------------

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """A versioned prompt file, e.g. "sort.v1" -> app/ai/prompts/sort.v1.md."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
