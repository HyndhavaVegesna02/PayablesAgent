"""One consolidated ablation table from report.json files only (CHG-048;
CHG-055): harness by scenario, success with its spread, the full-vs-bare
delta, each knock-out's paired drop and the component that earned the most.
A drop is shown only for a harness scored on more than half the scenarios,
and the page says how many runs each cell holds. check-evidence re-derives a
committed one from its parts."""

import json

from evals import report
from scripts import check_evidence


def _part(date, harnesses, budget=(10, 1000), status="COMPLETE", stopped=None):
    return {"meta": {"label": "x", "mode": "live", "model": "m", "prompt_version": "p", "commit": "c", "date": date,
                     "status": status, "stopped_because": stopped, "runs_per_scenario": 1,
                     "budget": {"calls": budget[0], "micro_usd": budget[1]}},
            "harnesses": {h: {"mechanics_only": False, "by_scenario": cells} for h, cells in harnesses.items()}}


def c(met, scored):
    return {"met": met, "scored": scored}


def test_drops_are_paired_on_the_scenarios_each_knock_out_was_scored_on():
    full = _part("2026-10-05T09:00:00+05:30", {"full": {"a": c(1, 1), "b": c(1, 1), "d": c(0, 1)}})
    ko = _part("2026-10-05T10:00:00+05:30", {"no_x": {"a": c(0, 1), "b": c(1, 1)},
                                              "no_y": {"d": c(0, 1)}})
    bare = _part("2026-10-05T11:00:00+05:30", {"bare": {"a": c(0, 1), "b": c(0, 1), "d": c(0, 1)}})
    rep = report.ablation_combine([("ko", ko), ("bare", bare), ("full", full)], "t")
    assert rep["drops"] == {"no_x": 0.5} and rep["lost"]["no_x"] == ["a"]  # paired on a and b
    assert rep["not_measured"] == {"no_y": 1}  # on d alone: one of three scenarios is not more than half
    assert rep["full_vs_bare"] == 0.667 and rep["paired_on"]["bare"] == 3 and rep["earned_most"] == ["no_x"]
    assert rep["harnesses"]["full"]["spread"] == [0.0, 1.0] and rep["spent"] == {"calls": 30, "micro_usd": 3000}
    assert list(rep["harnesses"]) == ["full", "bare", "no_x", "no_y"]


def test_a_knock_out_on_half_the_scenarios_or_fewer_is_not_measured_and_cannot_earn_the_most():
    full = _part("2026-10-05T09:00:00+05:30", {"full": {s: c(1, 1) for s in "abcd"}})
    ko = _part("2026-10-05T10:00:00+05:30", {"no_x": {"a": c(0, 1), "b": c(0, 1)},  # 2 of 4: half
                                              "no_y": {"a": c(1, 1), "b": c(1, 1), "c": c(0, 1)}})  # 3 of 4
    rep = report.ablation_combine([("full", full), ("ko", ko)], "t")
    assert rep["not_measured"] == {"no_x": 2} and rep["drops"] == {"no_y": 0.333}
    assert rep["earned_most"] == ["no_y"]  # no_x lost more where it ran, but it barely ran
    md = report.ablation_combined_markdown(rep)
    assert "| no_x | 2/4 | 1 | 0% | not measured live (2/4 scenarios) |" in md
    assert "| no_x | not measured live (2/4 scenarios) | n/a |" in md
    assert "| no_y | 33 | c |" in md
    assert "Left out: no_x, scored on half the scenarios or fewer." in md


def test_a_table_with_no_knock_out_measured_says_none_is_compared():
    full = _part("2026-10-05T09:00:00+05:30", {"full": {s: c(1, 1) for s in "abcd"}})
    ko = _part("2026-10-05T10:00:00+05:30", {"no_x": {"a": c(1, 1)}})
    md = report.ablation_combined_markdown(report.ablation_combine([("full", full), ("ko", ko)], "t"))
    assert "No knock-out was scored on more than half the scenarios, so none is compared here." in md
    assert "lowered outcome success" not in md


def test_earned_the_most_says_what_one_run_per_scenario_means():
    full = _part("2026-10-05T09:00:00+05:30", {"full": {s: c(3, 3) for s in "abcd"}})
    ko = _part("2026-10-05T10:00:00+05:30", {"no_x": {"a": c(0, 1), "b": c(1, 1), "c": c(1, 1), "d": c(1, 1)}})
    md = report.ablation_combined_markdown(report.ablation_combine([("full", full), ("ko", ko)], "t", "2-x/live"))
    assert "Knocking out **no_x** cost the most: 25 points." in md
    assert "It ran once per scenario, so 25 points is 1 scenario of the 4 no_x was paired on (a)." in md
    assert "[The offline ablation](../../2-harness-ablation/offline/report.md) runs every harness" in md
    assert "| full | 4/4 | 3 | 100% | — |" in md


def test_coverage_names_the_cells_that_hold_a_different_number_of_runs():
    full = _part("2026-10-05T09:00:00+05:30", {"full": {"a": c(3, 3), "b": c(3, 3), "k": c(2, 2)}})
    md = report.ablation_combined_markdown(report.ablation_combine([("full", full)], "t"))
    assert "| full | 3/3 | 3 (2 on k) | 100% | — |" in md


def test_the_sources_table_says_each_status_plainly_and_how_many_runs_each_gave():
    first = _part("2026-10-05T09:00:00+05:30", {"full": {"a": c(1, 1), "b": c(1, 1)}, "no_x": {"a": c(0, 0)}},
                  status="ABORTED", stopped="spend cap: Google refused the call (429) and waiting can't help: ...")
    later = _part("2026-10-05T10:00:00+05:30", {"no_x": {"a": c(1, 1), "b": c(0, 1)}})
    later["meta"]["budget"]["stopped"] = "cost cap reached: 9 micro-USD spent"  # its header says COMPLETE
    md = report.ablation_combined_markdown(report.ablation_combine([("raw-runs/p1", first), ("raw-runs/p2", later)],
                                                                   "t", "2-harness-ablation/live"))
    assert ("| [`p1`](../../raw-runs/p1/report.md) | full, no_x | live | m | p | c | 2026-10-05T09:00:00+05:30 | "
            "Stopped: Google's project spending cap (429) | 1 | 2 | 10 | 1000 |") in md
    assert "| Stopped by our budget guard (cost cap) | 1 | 2 | 10 | 1000 |" in md
    assert "waiting can't help" not in md
    assert "A stopped invocation's finished runs are valid, and they are counted here" in md


def test_a_later_scored_invocation_replaces_an_earlier_errored_cell():
    first = _part("2026-10-05T09:00:00+05:30", {"bare": {"a": c(0, 0), "b": c(1, 1)}})  # a errored: unscored
    later = _part("2026-10-05T10:00:00+05:30", {"bare": {"a": c(1, 1)}})
    rep = report.ablation_combine([("later", later), ("first", first)], "t")
    assert rep["cells"]["bare"]["a"]["source"] == "later" and rep["cells"]["bare"]["b"]["source"] == "first"


def test_check_evidence_re_derives_a_consolidated_table_and_sees_a_hand_edit(tmp_path, monkeypatch):
    evals = tmp_path / "docs" / "evals"
    parts = [("raw-runs/p1", _part("2026-10-05T09:00:00+05:30", {"full": {"a": c(1, 1)}})),
             ("raw-runs/p2", _part("2026-10-05T10:00:00+05:30", {"no_x": {"a": c(0, 1)}}))]
    for name, rep in parts:
        (evals / name).mkdir(parents=True)
        (evals / name / "report.json").write_text(json.dumps(rep), encoding="utf-8")
    out = report.write_ablation_combined(report.ablation_combine(parts, "t", "2-harness-ablation/live"),
                                         evals / "2-harness-ablation" / "live")
    monkeypatch.setattr(check_evidence, "ROOT", tmp_path)
    monkeypatch.setattr(check_evidence, "EVALS", evals)
    (kind, path, meta), = [x for x in check_evidence.committed() if x[0] == "ablation-combined"]
    fresh = check_evidence.regenerate(kind, meta, tmp_path / "fresh", "2-harness-ablation/live")
    assert check_evidence.differences(path, fresh) == []
    md = out / "report.md"
    md.write_text(md.read_text(encoding="utf-8").replace("cost the most", "cost the least"), encoding="utf-8")
    assert check_evidence.differences(path, fresh) != []


def test_a_context_only_row_is_left_out_like_a_mechanics_only_one():
    """Review round 1: a fixture ablation's no_case_file row is "context only"; the table leaves it out."""
    part = _part("2026-10-05T09:00:00+05:30", {"full": {"a": c(1, 1)}, "no_case_file": {"a": c(1, 1)}})
    part["harnesses"]["no_case_file"]["context_only"] = True
    rep = report.ablation_combine([("p", part)], "t")
    assert list(rep["harnesses"]) == ["full"] and rep["drops"] == {}


def test_the_committed_live_table_measures_only_the_knock_outs_scored_on_most_scenarios():
    """CHG-055: all_tools and no_planner stopped on their caps after one scenario each; they are not measured, and
    the headline stays full against bare. Every figure is read from the table's own report.json."""
    page = check_evidence.EVALS / "2-harness-ablation" / "live"
    rep = json.loads((page / "report.json").read_text(encoding="utf-8"))
    md = (page / "report.md").read_text(encoding="utf-8")
    n = len(rep["scenarios"])
    for h, x in rep["harnesses"].items():
        if h != "full":
            assert (h in rep["not_measured"]) == (2 * len(x["scenarios_scored"]) <= n)
    assert set(rep["not_measured"]) == {"all_tools", "no_planner"}
    assert set(rep["earned_most"]).isdisjoint(rep["not_measured"])
    assert md.splitlines()[2].startswith(f"**Headline:** the harness itself, the full system against the bare harness "
                                         f"on the same model, paired on the {rep['paired_on']['bare']} scenarios")
    assert "once per scenario" in md and "[The offline ablation](../offline/report.md)" in md
