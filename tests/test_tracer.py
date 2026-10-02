import json

from app.clock import FakeClock
from app.trace.tracer import Tracer
from app.trace.view import find_run_file, format_step


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
