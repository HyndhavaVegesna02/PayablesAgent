import pytest
from pydantic import ValidationError

from app.config import AppConfig, Settings, load_app_config


def test_settings_loads_defaults_with_no_env(monkeypatch):
    for var in (
        "GEMINI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        "FERNET_KEY", "SESSION_SECRET", "DATABASE_PATH", "DATA_DIR", "TRACE_DIR",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)
    assert settings.database_path == "./data/cashflow.db"
    assert settings.trace_dir == "./traces"
    assert settings.mail_source == "eml_folder"


def test_settings_fails_fast_on_blank_database_path(monkeypatch):
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_PATH"):
        Settings(_env_file=None, database_path="")


def test_settings_reads_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "/tmp/custom.db")
    settings = Settings(_env_file=None)
    assert settings.database_path == "/tmp/custom.db"


def test_load_app_config_parses_yaml(tmp_path):
    (tmp_path / "config.yaml").write_text(
        """
model:
  id: gemini-3.8-flash
  thinking: {sort: low, extract: medium, voice: medium, exception: medium, explain: low}
prompts:
  version: 2026-10-02.1
escalation:
  max_steps: 6
  default_stake_paise: 5000000
  max_validation_failures: 2
matching:
  window_days: 3
mail:
  poll_minutes: 5
alerts:
  min_minutes_between_emails: 30
""",
        encoding="utf-8",
    )
    config = load_app_config(tmp_path / "config.yaml")
    assert isinstance(config, AppConfig)
    assert config.model.id == "gemini-3.8-flash"
    assert config.model.thinking.extract == "medium"
    assert config.escalation.default_stake_paise == 5_000_000


def test_load_app_config_rejects_unknown_thinking_level(tmp_path):
    (tmp_path / "config.yaml").write_text(
        """
model:
  id: gemini-3.8-flash
  thinking: {sort: minimal, extract: medium, voice: medium, exception: medium, explain: low}
prompts:
  version: 2026-10-02.1
escalation: {max_steps: 6, default_stake_paise: 5000000, max_validation_failures: 2}
matching: {window_days: 3}
mail: {poll_minutes: 5}
alerts: {min_minutes_between_emails: 30}
""",
        encoding="utf-8",
    )
    # "minimal" is explicitly not supported by Gemini 3.8 Flash (TDD Part 1, "AI model")
    with pytest.raises(ValidationError, match="minimal"):
        load_app_config(tmp_path / "config.yaml")
