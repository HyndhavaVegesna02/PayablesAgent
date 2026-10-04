"""One report from several invocations (batch 10, CHG-035). The 11x5 live
run stopped on a 429 after scenarios 01-07; 08-11 (and 04 again, after PO
D28) run later as their own invocation. The combined page is generated from
the two report.json files, never typed, and make check-evidence re-derives it."""

import copy
import json

from evals import report
from scripts import check_evidence

PART1 = "2026-10-04-live-baseline"


def _parts():
    first = json.loads((check_evidence.EVALS / PART1 / "report.json").read_text(encoding="utf-8"))
    second = copy.deepcopy(first)
    keep = {"04-hinglish-voice-note", "08-drift-with-no-explanation"}
    second["scenarios"] = [dict(r, passed=r["runs"] - r["errored"], failed=0) for r in second["scenarios"]
                           if r["scenario"] in keep]
    second["runs"] = [r for r in second["runs"] if r["scenario"] in keep]
    second["meta"].update(commit="abc1234", date="2026-10-05T09:00:00+05:30", status="COMPLETE", stopped_because=None,
                          budget={"calls": 120, "micro_usd": 400_000})
    return [(PART1, first), ("2026-10-05-live-baseline-part2", second)]


def test_the_latest_report_to_run_a_scenario_wins_and_the_row_says_so():
    combined = report.combine(_parts(), "baseline-11x5")
    by_name = {r["scenario"]: r for r in combined["scenarios"]}
    assert by_name["04-hinglish-voice-note"]["source"] == "2026-10-05-live-baseline-part2"
    assert by_name["01-debit-alert-for-a-planned-payment"]["source"] == PART1
    assert [r["scenario"] for r in combined["scenarios"]] == sorted(by_name)
    t = combined["totals"]
    assert t["runs"] == sum(r["runs"] for r in combined["scenarios"])
    assert t["spent"] == {"calls": 254 + 120, "micro_usd": 805_565 + 400_000}  # every invocation's spend


def test_the_page_names_every_source_and_its_status():
    md = report.combined_markdown(report.combine(_parts(), "baseline-11x5"))
    assert md.startswith("# Eval report: baseline-11x5 (combined)")
    assert f"| `{PART1}` | live | gemini-3.8-flash | 2026-10-04.2 | aba59bd |" in md
    assert "| ABORTED (rate limited: a 429 outlasted 5 backoffs) | 5 | 254 | 805565 |" in md
    assert "| Scenario | From | Success |" in md and "| `2026-10-05-live-baseline-part2` |" in md


def test_check_evidence_re_derives_a_combined_report_and_sees_a_hand_edit(tmp_path, monkeypatch):
    parts = _parts()
    evals = tmp_path / "docs" / "evals"
    for name, rep in parts:
        (evals / name).mkdir(parents=True)
        (evals / name / "report.json").write_text(json.dumps(rep), encoding="utf-8")
    out = report.write_combined(report.combine(parts, "baseline-11x5"), evals / "2026-10-05-live-baseline-11x5")
    monkeypatch.setattr(check_evidence, "ROOT", tmp_path)
    monkeypatch.setattr(check_evidence, "EVALS", evals)
    (kind, path, meta), = [c for c in check_evidence.committed() if c[0] == "combined"]
    fresh = check_evidence.regenerate(kind, meta, tmp_path / "fresh")
    assert check_evidence.differences(path, fresh) == []
    md = out / "report.md"
    md.write_text(md.read_text(encoding="utf-8").replace("runs passed", "runs passed!"), encoding="utf-8")
    assert check_evidence.differences(path, fresh) == ["docs/evals/2026-10-05-live-baseline-11x5/report.md: "
                                                       "line 10 differs"]
