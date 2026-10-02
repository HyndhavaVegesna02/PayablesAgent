"""Two independent configuration sources (TDD Part 2, "Dependencies and
environment" and "Tracing, configuration and security"):

- `Settings` — environment variables / `.env`: secrets and machine-specific
  paths. Loaded with pydantic-settings.
- `AppConfig` — `config.yaml`: model id, thinking levels, prompt version,
  escalation/matching/mail/alert thresholds. Checked by Pydantic at startup;
  changing anything under `model` or `prompts` requires the scenario suite to
  run in CI before merge (enforced by review, not by this module).

Secrets with no production default (GEMINI_API_KEY, GOOGLE_CLIENT_SECRET,
FERNET_KEY, SESSION_SECRET, ...) are intentionally *not* hard-required yet:
no code in this phase calls Gemini, Gmail or the encryption layer. They
default to "" and become load-bearing as the phases that use them land. The
three path settings below are already load-bearing (the DB, trace writer and
future document store all read them today), so they fail fast when blank.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ThinkingLevel = Literal["low", "medium", "high"]  # "minimal" is not supported, see TDD Part 1


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    gemini_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/gmail/callback"
    fernet_key: str = ""
    session_secret: str = ""
    smtp_host: str = ""
    smtp_port: int | None = None
    smtp_user: str = ""
    smtp_password: str = ""
    alert_from: str = ""
    database_path: str = "./data/cashflow.db"
    data_dir: str = "./data/files"
    trace_dir: str = "./traces"
    mail_source: Literal["gmail", "eml_folder"] = "eml_folder"
    test_inbox_path: str = "./fixtures/test_inbox"
    # The web app's cookie is marked Secure only behind https (local http can't use it).
    cookie_secure: bool = False
    # Demo logins created by `make seed` (dev defaults; documented in .env.example).
    seed_owner_password: str = "owner-demo-pass"
    seed_helper_password: str = "helper-demo-pass"
    # A fixed "now" for the web app and the seed, e.g. 2026-10-12T09:00:00+05:30 to
    # demo the worked example on its own Monday. Blank means real time.
    demo_now: str = ""
    # DEMO_AI=fixtures: in a demo, the worker answers from the test inbox's canned
    # replies instead of Gemini (batch 3 plan, D15). Needs DEMO_NOW.
    demo_ai: Literal["", "fixtures"] = ""

    @field_validator("demo_now")
    @classmethod
    def _demo_now_has_offset(cls, value: str) -> str:
        if value.strip():
            from datetime import datetime

            if datetime.fromisoformat(value.strip()).tzinfo is None:
                raise ValueError("DEMO_NOW needs a UTC offset, like 2026-10-12T09:00:00+05:30")
        return value.strip()

    @field_validator("database_path", "data_dir", "trace_dir")
    @classmethod
    def _not_blank(cls, value: str, info) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name.upper()} must not be blank")
        return value

    @model_validator(mode="after")
    def _fixture_ai_only_in_a_demo(self):
        if self.demo_ai == "fixtures" and not self.demo_now:
            raise ValueError("DEMO_AI=fixtures is for demos only: set DEMO_NOW too (see .env.example)")
        return self

    @field_validator("smtp_port", mode="before")
    @classmethod
    def _blank_port_is_none(cls, value):
        # An unset SMTP_PORT in .env arrives as "" (not missing), which int
        # parsing rejects outright. Blank means "not configured yet".
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ModelThinking(BaseModel):
    sort: ThinkingLevel
    extract: ThinkingLevel
    voice: ThinkingLevel
    exception: ThinkingLevel
    explain: ThinkingLevel


class ModelPricing(BaseModel):
    """Gemini list prices in integer micro-USD per million tokens (batch 2 plan,
    Q2): no float holds a cost. Output includes thinking tokens."""

    input_micro_usd_per_mtok: int = Field(ge=0)
    output_micro_usd_per_mtok: int = Field(ge=0)


class ModelConfig(BaseModel):
    id: str
    thinking: ModelThinking
    pricing: ModelPricing


class AIConfig(BaseModel):
    timeout_ms: int = Field(gt=0)


class PromptsConfig(BaseModel):
    version: str


class EscalationConfig(BaseModel):
    max_steps: int = Field(gt=0)
    default_stake_paise: int = Field(ge=0)
    max_validation_failures: int = Field(gt=0)


class MatchingConfig(BaseModel):
    window_days: int = Field(gt=0)


class MailConfig(BaseModel):
    poll_minutes: int = Field(gt=0)


class AlertsConfig(BaseModel):
    min_minutes_between_emails: int = Field(ge=0)


class AppConfig(BaseModel):
    model: ModelConfig
    ai: AIConfig
    prompts: PromptsConfig
    escalation: EscalationConfig
    matching: MatchingConfig
    mail: MailConfig
    alerts: AlertsConfig


def load_app_config(path: str | Path = "config.yaml") -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw)
