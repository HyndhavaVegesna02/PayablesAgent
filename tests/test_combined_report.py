"""One report from several invocations (batch 10, CHG-035; CHG-055). The 11x5
live run stopped on a 429 after scenarios 01-07; 08-11 (and 04 again, after PO
D28) run later as their own invocation. The combined page is generated from
the report.json files, never typed, and make check-evidence re-derives it. It
opens with what it covers, including every scenario a later invocation ran
again and what each earlier run of it showed, and it says each source's
status in plain words."""

import copy
import json
import shutil

import pytest

from evals import report
from scripts import check_evidence

RAW = check_evidence.EVALS / "raw-runs"
PART1 = "raw-runs/2026-10-04-live-baseline"
PART2 = "raw-runs/2026-10-05-live-baseline-part2"


def _parts():
    first = json.loads((RAW / "2026-10-04-live-baseline" / "report.json").read_text(encoding="utf-8"))
    second = copy.deepcopy(first)
    keep = {"04-hinglish-voice-note", "08-drift-with-no-explanation"}
    second["scenarios"] = [dict(r, passed=r["runs"] - r["errored"], failed=0) for r in second["scenarios"]
                           if r["scenario"] in keep]
    second["runs"] = [r for r in second["runs"] if r["scenario"] in keep]
    second["meta"].update(commit="abc1234", date="2026-10-05T09:00:00+05:30", status="COMPLETE", stopped_because=None,
                          budget={"calls": 120, "micro_usd": 400_000})
    return [(PART1, first), (PART2, second)]


def test_the_latest_report_to_run_a_scenario_wins_and_the_row_says_so():
    combined = report.combine(_parts(), "baseline-11x5")
    by_name = {r["scenario"]: r for r in combined["scenarios"]}
    assert by_name["04-hinglish-voice-note"]["source"] == PART2
    assert by_name["01-debit-alert-for-a-planned-payment"]["source"] == PART1
    assert [r["scenario"] for r in combined["scenarios"]] == sorted(by_name)
    t = combined["totals"]
    assert t["runs"] == sum(r["runs"] for r in combined["scenarios"])
    assert t["spent"] == {"calls": 254 + 120, "micro_usd": 805_565 + 400_000}  # every invocation's spend


def test_the_page_names_every_source_its_plain_status_and_the_runs_it_gave():
    md = report.combined_markdown(report.combine(_parts(), "baseline-11x5", "1-eval-report/live-11x5"))
    assert md.startswith("# Eval report: baseline-11x5 (combined)")
    link = "[`2026-10-04-live-baseline`](../../raw-runs/2026-10-04-live-baseline/report.md)"
    assert f"| {link} | live | gemini-3.8-flash | 2026-10-04.2 | aba59bd |" in md
    # 01-03 and 05-07 come from the first invocation; 08 errored there and in the second, so it gave no run
    assert "| Stopped: Google kept refusing (429) after 5 backoffs | 5 | 30 | 254 | 805565 |" in md
    assert "| Complete | 5 | 5 | 120 | 400000 |" in md
    assert "rate limited: a 429" not in md  # the raw reason stays in the source report
    assert "A stopped invocation's finished runs are valid, and they are counted here" in md
    assert "| Scenario | From | Success |" in md
    assert "| [`2026-10-05-live-baseline-part2`](../../raw-runs/2026-10-05-live-baseline-part2/report.md) |" in md


def test_the_coverage_line_comes_first_and_names_every_scenario_run_again_with_each_result():
    combined = report.combine(_parts(), "baseline-11x5")
    lines = report.combined_markdown(combined).splitlines()
    assert lines[2].startswith("**Coverage:** 35 of 40 planned runs scored (8 scenarios × 5 runs), from 2 "
                               "invocations at commits aba59bd and abc1234.")
    assert lines[4].startswith("**Totals:** 35 of 35 finished runs passed (100%), 1 errored;")  # 08's one run
    assert ("04-hinglish-voice-note: 4/5 in `2026-10-04-live-baseline`, then 5/5 in "
            "`2026-10-05-live-baseline-part2`") in lines[2]
    assert ("08-drift-with-no-explanation: no run finished (1 errored) in `2026-10-04-live-baseline`, then no run "
            "finished (1 errored) in `2026-10-05-live-baseline-part2`") in lines[2]
    assert combined["coverage"]["planned"] == 40 and combined["coverage"]["scored"] == 35
    assert "5 planned runs no invocation finished." in "\n".join(lines)


def test_the_totals_count_passes_over_the_runs_that_finished():
    """PO, CHG-055: "34 of 36 runs passed (97% of the runs that finished)" mixed two denominators."""
    first = json.loads((RAW / "2026-10-04-live-baseline" / "report.json").read_text(encoding="utf-8"))
    assert "**Totals:** 34 of 35 finished runs passed (97%), 1 errored;" in report.markdown(first)


@pytest.mark.parametrize(("status", "stopped", "plain"), [
    ("COMPLETE", None, "Complete"),
    ("ABORTED", "cost cap reached: 700642 micro-USD spent, and the next call could cost 50316 (cap 750000)",
     "Stopped by our budget guard (cost cap)"),
    ("ABORTED", "call cap reached: 600 of 600 calls used", "Stopped by our budget guard (call cap)"),
    ("ABORTED", "spend cap: Google refused the call (429) and waiting can't help: Your project has exceeded its "
                "monthly spending cap.", "Stopped: Google's project spending cap (429)"),
    ("ABORTED", "rate limited: a 429 outlasted 5 backoffs", "Stopped: Google kept refusing (429) after 5 backoffs"),
    ("ABORTED", "credits depleted: Google refused the call (402)", "Stopped: Google's prepaid credits ran out (402)"),
])
def test_a_status_in_plain_words_is_true_to_the_recorded_reason(status, stopped, plain):
    assert report.plain_status(status, stopped) == plain


def test_a_header_that_says_complete_still_shows_the_guards_stop():
    """The ablation checks its guard only before a run, so an invocation whose last run the guard stopped can say
    COMPLETE; the guard's own record says why it stopped, and the plain status follows that."""
    meta = {"status": "COMPLETE", "stopped_because": None,
            "budget": {"stopped": "cost cap reached: 899154 micro-USD spent, and the next call could cost 151547"}}
    assert report.plain_status(meta["status"], report.stopped_reason(meta)) == "Stopped by our budget guard (cost cap)"


def _laid_out(tmp_path, monkeypatch, parts):
    evals = tmp_path / "docs" / "evals"
    for name, rep in parts:
        (evals / name).mkdir(parents=True)
        (evals / name / "report.json").write_text(json.dumps(rep), encoding="utf-8")
    monkeypatch.setattr(check_evidence, "ROOT", tmp_path)
    monkeypatch.setattr(check_evidence, "EVALS", evals)
    return evals


def test_check_evidence_re_derives_a_combined_report_and_sees_a_hand_edit(tmp_path, monkeypatch):
    parts = _parts()
    evals = _laid_out(tmp_path, monkeypatch, parts)
    out = report.write_combined(report.combine(parts, "baseline-11x5", "1-eval-report/live-t"),
                                evals / "1-eval-report" / "live-t")
    (kind, path, meta), = [c for c in check_evidence.committed() if c[0] == "combined"]
    fresh = check_evidence.regenerate(kind, meta, tmp_path / "fresh", "1-eval-report/live-t")
    assert check_evidence.differences(path, fresh) == []
    md = out / "report.md"
    md.write_text(md.read_text(encoding="utf-8").replace("finished runs passed", "finished runs passed!"),
                  encoding="utf-8")
    assert check_evidence.differences(path, fresh) == ["docs/evals/1-eval-report/live-t/report.md: line 5 differs"]


def test_check_evidence_sees_a_combined_page_moved_without_regenerating_its_links(tmp_path, monkeypatch):
    parts = _parts()
    evals = _laid_out(tmp_path, monkeypatch, parts)
    report.write_combined(report.combine(parts, "baseline-11x5", "1-eval-report/live-t"),
                          evals / "1-eval-report" / "live-t")
    (evals / "1-eval-report" / "x").mkdir()
    shutil.move(evals / "1-eval-report" / "live-t", evals / "1-eval-report" / "x" / "live-t")  # one level deeper
    (kind, path, meta), = [c for c in check_evidence.committed() if c[0] == "combined"]
    fresh = check_evidence.regenerate(kind, meta, tmp_path / "fresh", "1-eval-report/x/live-t")
    assert check_evidence.differences(path, fresh) != []  # its links still point from where it was


def test_the_committed_11x5_page_says_what_every_raw_run_of_scenario_04_showed():
    """CHG-055: 55/55 never appears without the replaced rows; each result is read from the raw run's own report."""
    page = check_evidence.EVALS / "1-eval-report" / "live-11x5"
    md = (page / "report.md").read_text(encoding="utf-8")
    combined = json.loads((page / "report.json").read_text(encoding="utf-8"))
    told = []
    for s in combined["meta"]["sources"]:
        raw = json.loads((check_evidence.EVALS / s["report"] / "report.json").read_text(encoding="utf-8"))
        (row,) = [r for r in raw["scenarios"] if r["scenario"] == "04-hinglish-voice-note"]
        told.append(f"{row['passed']}/{row['runs'] - row['errored']} in `{s['report'].split('/')[-1]}`")
    coverage = md.splitlines()[2]
    assert coverage == report.coverage_line(combined)
    assert f"04-hinglish-voice-note: {told[0]}, {told[1]}, then {told[2]}" in coverage
    t = combined["totals"]
    assert md.splitlines()[4].startswith(f"**Totals:** {t['passed']} of {t['runs'] - t['errored']} finished runs passed")
