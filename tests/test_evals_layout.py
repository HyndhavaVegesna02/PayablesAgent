"""docs/evals is laid out by deliverable (CHG-055): a numbered folder per
deliverable, and raw-runs/ for every invocation those pages were built from.
New runs land in raw-runs/ or with the workflow reports, never at the top, and
check-evidence finds every report in the new layout."""

import argparse
import re

import pytest

from evals import ablation, layout, report, runner, workflow
from scripts import check_evidence


class _Parsed(Exception):
    pass


def _parsed(monkeypatch, main, argv):
    """The arguments a command line parses to, without running it."""
    real = argparse.ArgumentParser.parse_args

    def capture(self, args=None, namespace=None):
        raise _Parsed(real(self, args, namespace))

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    with pytest.raises(_Parsed) as e:
        main(argv)
    return e.value.args[0]


def test_new_suite_and_ablation_runs_go_to_raw_runs_and_workflows_to_their_folder(monkeypatch):
    assert _parsed(monkeypatch, runner.main, ["--ai", "fixtures"]).out == layout.RAW_RUNS
    assert _parsed(monkeypatch, ablation.main, ["--ai", "fixtures"]).out == layout.RAW_RUNS
    assert _parsed(monkeypatch, workflow.main, ["--ai", "fixtures"]).out == layout.WORKFLOWS
    assert layout.RAW_RUNS.parent == layout.WORKFLOWS.parent == layout.EVALS


def test_a_combined_page_names_its_own_folder():
    with pytest.raises(SystemExit):
        report.main(["combine", "a", "b", "--label", "x"])  # no --out: it would land nowhere in particular


def test_nothing_but_the_layout_sits_at_the_top_of_docs_evals():
    top = sorted(p.name for p in layout.EVALS.iterdir())
    shown = [n for n in top if n[0].isdigit()]
    assert shown == ["1-eval-report", "2-harness-ablation", "3-improvement-and-regression", "4-end-to-end-workflows"]
    assert set(top) - set(shown) <= {"README.md", "raw-runs", "superseded", "invalid"}


def test_check_evidence_finds_every_reproducible_report_in_the_layout():
    found = sorted(p.relative_to(check_evidence.EVALS).as_posix() for _, p, _ in check_evidence.committed())
    assert found == [
        "1-eval-report/live-11x5/report.json",
        "1-eval-report/offline-14x5/report.json",
        "2-harness-ablation/live/report.json",
        "2-harness-ablation/offline/report.json",
        "3-improvement-and-regression/regression-caught/report.json",
        "4-end-to-end-workflows/workflow-A-2026-10-04.json",
        "4-end-to-end-workflows/workflow-B-2026-10-04.json",
        "raw-runs/2026-10-04-live-ablation-v1/report.json",
    ]


_TRACE_PATH = re.compile(r"(?:^|[/\\])traces[/\\]|\.jsonl$|^docs[/\\]evals[/\\]")


def recorded_paths(value, out=None) -> list[str]:
    """Every string in a report.json that names a trace or a docs/evals path."""
    out = [] if out is None else out
    if isinstance(value, dict):
        for v in value.values():
            recorded_paths(v, out)
    elif isinstance(value, list):
        for v in value:
            recorded_paths(v, out)
    elif isinstance(value, str) and " " not in value and _TRACE_PATH.search(value):
        out.append(value)
    return out


def dead_trace_paths(report_json) -> list[str]:
    import json

    paths = recorded_paths(json.loads(report_json.read_text(encoding="utf-8")))
    return [p for p in paths if not any((base / p).exists() for base in (report_json.parent, layout.ROOT))]


def test_every_trace_path_a_report_records_still_resolves_after_the_move():
    """PO, CHG-055 AC7: none records one today (kept traces sit in a traces/ folder beside their report, and the
    pages that cite them are link-checked), so this guards the next report that does."""
    reports = [p for pattern in ("report.json", "*-report.json", "workflow-*.json")
               for root in layout.report_roots() for p in root.rglob(pattern)]
    assert len(reports) >= 30
    assert {p.as_posix(): dead_trace_paths(p) for p in reports if dead_trace_paths(p)} == {}


def test_the_trace_path_check_sees_a_dead_one(tmp_path):
    import json

    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "job-1-attempt-1.jsonl").write_text("{}\n", encoding="utf-8")
    report_json = tmp_path / "report.json"
    report_json.write_text(json.dumps({"runs": [{"trace": "traces/job-1-attempt-1.jsonl"},
                                                {"trace": "traces/gone.jsonl"}],
                                       "note": "not in the database, its WAL, the traces or the stored files"}),
                           encoding="utf-8")
    assert dead_trace_paths(report_json) == ["traces/gone.jsonl"]


def test_a_combined_pages_sources_are_raw_runs():
    import json

    for page in ("1-eval-report/live-11x5", "2-harness-ablation/live"):
        meta = json.loads((layout.EVALS / page / "report.json").read_text(encoding="utf-8"))["meta"]
        assert meta["folder"] == page
        assert all(s["report"].startswith("raw-runs/") for s in meta["sources"])
