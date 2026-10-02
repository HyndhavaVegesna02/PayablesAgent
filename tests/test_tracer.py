import json

from app.clock import FakeClock
from app.trace.tracer import Tracer
from app.trace.view import find_run_file, format_step, main


def test_step_writes_one_json_line_with_part1_fields(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    clock = FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")))

    tracer = Tracer(run_id="job-1-attempt-1", trace_dir=tmp_path, clock=clock)
    tracer.step(
        input_ref="gmail:msg-123",
        model="gemini-3.8-flash",
        thinking="low",
        tool="search_gmail",
        arguments={"query": "from:bank"},
        result="3 messages found",
        validation="passed",
        retries=0,
        escalation_rule=None,
        tokens={"input": 120, "output": 40},
        cost=0.0004,
    )

    expected_path = tmp_path / "2026-10-12" / "job-1-attempt-1.jsonl"
    assert expected_path.exists()

    lines = expected_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    entry = json.loads(lines[0])
    for field in (
        "run_id", "step", "timestamp", "input_ref", "model", "thinking",
        "tool", "arguments", "result", "validation", "retries",
        "escalation_rule", "tokens", "cost",
    ):
        assert field in entry, f"missing field {field}"
    assert entry["run_id"] == "job-1-attempt-1"
    assert entry["step"] == 1


def test_multiple_steps_increment_and_append(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    clock = FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    tracer = Tracer(run_id="job-2-attempt-1", trace_dir=tmp_path, clock=clock)
    tracer.step(tool="a")
    tracer.step(tool="b")

    path = tmp_path / "2026-10-12" / "job-2-attempt-1.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["step"] == 1
    assert json.loads(lines[1])["step"] == 2


def test_sensitive_fields_are_redacted(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    clock = FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    tracer = Tracer(run_id="job-3-attempt-1", trace_dir=tmp_path, clock=clock)
    tracer.step(
        tool="gmail_oauth",
        arguments={"refresh_token": "secret-value", "password": "hunter2", "ok": "fine"},
    )

    path = tmp_path / "2026-10-12" / "job-3-attempt-1.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert entry["arguments"]["refresh_token"] == "***REDACTED***"
    assert entry["arguments"]["password"] == "***REDACTED***"
    assert entry["arguments"]["ok"] == "fine"


def _one_step(tmp_path, **fields):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    clock = FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    Tracer(run_id="r", trace_dir=tmp_path, clock=clock).step(**fields)
    return json.loads((tmp_path / "2026-10-12" / "r.jsonl").read_text(encoding="utf-8"))


def test_top_level_fields_are_redacted_too_but_tokens_is_kept(tmp_path):
    # Part 1's trace has a `tokens` field; it holds counts, not credentials.
    entry = _one_step(tmp_path, api_key="k", password="p",
                      tokens={"input": 120, "output": 40, "thoughts": 7})
    assert (entry["api_key"], entry["password"]) == ("***REDACTED***", "***REDACTED***")
    assert entry["tokens"] == {"input": 120, "output": 40, "thoughts": 7}


SENSITIVE = [
    "api_key", "apiKey", "client-secret", "refresh_token_enc", "password_hash", "GEMINI_API_KEY",
    # compounds written as one word (batch 2 review): they end in a sensitive word
    "apikey", "APIKEY", "accesstoken", "dbpassword", "fernetkey", "PRIVATEKEY", "passwords", "keys",
    "monkey",  # over-redaction is the safe side
]
KEPT = ["tokens", "input_tokens", "keyboard", "ok", "thoughts", "input_ref"]


def test_redaction_matches_word_endings_in_any_naming_style(tmp_path):
    entry = _one_step(tmp_path, arguments={**{k: "secret" for k in SENSITIVE}, **{k: 1 for k in KEPT}})
    redacted = {k for k, v in entry["arguments"].items() if v == "***REDACTED***"}
    assert redacted == set(SENSITIVE)


def test_find_run_file_locates_by_run_id_across_dates(tmp_path):
    (tmp_path / "2026-10-12").mkdir()
    target = tmp_path / "2026-10-12" / "run-xyz.jsonl"
    target.write_text('{"run_id": "run-xyz", "step": 1}\n', encoding="utf-8")

    found = find_run_file(tmp_path, "run-xyz")
    assert found == target


def test_format_step_is_human_readable():
    entry = {
        "run_id": "r1", "step": 1, "timestamp": "2026-10-12T09:00:00+05:30",
        "tool": "search_gmail", "result": "3 messages found",
    }
    text = format_step(entry)
    assert "step 1" in text
    assert "search_gmail" in text
    assert "3 messages found" in text


def test_main_prints_a_run_found_via_trace_dir_env_var(tmp_path, monkeypatch, capsys):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("TRACE_DIR", str(tmp_path))
    clock = FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    Tracer(run_id="cli-run-1", trace_dir=tmp_path, clock=clock).step(tool="search_gmail")

    exit_code = main(["cli-run-1"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "step 1" in out
    assert "search_gmail" in out


def test_main_returns_1_for_an_unknown_run_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRACE_DIR", str(tmp_path))
    exit_code = main(["does-not-exist"])
    assert exit_code == 1


def test_main_returns_2_with_no_args(capsys):
    assert main([]) == 2


def test_the_viewer_falls_back_to_the_settings_trace_dir(tmp_path, monkeypatch, capsys):
    import app.trace.view as view_module

    (tmp_path / "2026-10-12").mkdir()
    (tmp_path / "2026-10-12" / "r9.jsonl").write_text('{"run_id": "r9", "step": 1, "tool": "x"}\n',
                                                      encoding="utf-8")
    monkeypatch.delenv("TRACE_DIR", raising=False)
    monkeypatch.setattr(view_module, "Settings", lambda: type("S", (), {"trace_dir": str(tmp_path)})())
    assert view_module.main(["r9"]) == 0
    assert "tool=x" in capsys.readouterr().out
