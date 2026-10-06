"""make check-evidence (CHG-032): a committed fixture-mode report must say
what the code emits, below its commit and date. These tests check the
comparison and the discovery; the full regeneration runs in the target itself,
at batch close, not in make test."""

import json

from scripts import check_evidence


def _report(folder, commit, date, body):
    folder.mkdir(parents=True)
    meta = {"mode": "fixtures", "label": "baseline", "commit": commit, "date": date}
    (folder / "report.json").write_text(json.dumps({"meta": meta, "totals": body}, indent=1), encoding="utf-8")
    (folder / "report.md").write_text(f"| fixtures | {commit} | {date} |\n\n{body}\n", encoding="utf-8")
    return folder / "report.json"


def test_only_the_commit_and_date_may_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(check_evidence, "ROOT", tmp_path)
    old = _report(tmp_path / "old", "2142c95", "2026-10-04T04:13:49+05:30", "55 of 55")
    same = _report(tmp_path / "same", "7ad9d92", "2026-10-05T08:10:00+05:30", "55 of 55")
    other = _report(tmp_path / "other", "7ad9d92", "2026-10-05T08:10:00+05:30", "54 of 55")
    assert check_evidence.differences(old, same) == []
    assert check_evidence.differences(old, other) == ["old/report.json: line 8 differs",
                                                       "old/report.md: line 3 differs"]


def test_every_fixture_mode_report_is_found_and_live_and_superseded_ones_are_not():
    found = {(kind, path.relative_to(check_evidence.EVALS).as_posix()) for kind, path, _ in check_evidence.committed()}
    kinds = {kind for kind, _ in found}
    assert kinds == {"suite", "ablation", "workflow", "combined", "ablation-combined"}  # derived pages re-derived
    assert all("superseded" not in p and "invalid" not in p and ("live" not in p or k in ("combined",
               "ablation-combined")) for k, p in found)
    assert ("suite", "3-improvement-and-regression/regression-caught/report.json") in found


def test_the_target_and_the_batch_close_gate_run_it():
    root = check_evidence.ROOT
    assert "check-evidence:\n\tuv run python scripts/check_evidence.py" in (root / "Makefile").read_text(encoding="utf-8")
    assert "`make check-evidence` -> exit 0" in (root / ".yourteam" / "definition-of-done.md").read_text(encoding="utf-8")
    assert "check-evidence" not in (root / "Makefile").read_text(encoding="utf-8").split("\ntest:")[1].split("\n\n")[0]
