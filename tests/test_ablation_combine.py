"""One consolidated ablation table from report.json files only (CHG-048):
harness by scenario, success with its spread, the full-vs-bare delta, each
knock-out's paired drop and the component that earned the most. check-evidence
re-derives a committed one from its parts."""

import json

from evals import report
from scripts import check_evidence


def _part(date, harnesses, budget=(10, 1000)):
    return {"meta": {"label": "x", "mode": "live", "model": "m", "prompt_version": "p", "commit": "c", "date": date,
                     "status": "COMPLETE", "stopped_because": None, "runs_per_scenario": 1,
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
    assert rep["drops"] == {"no_x": 0.5, "no_y": 0.0}  # no_y on d only, where full also failed: no drop
    assert rep["full_vs_bare"] == 0.667 and rep["earned_most"] == ["no_x"]
    assert rep["harnesses"]["full"]["spread"] == [0.0, 1.0] and rep["spent"] == {"calls": 30, "micro_usd": 3000}
    assert list(rep["harnesses"]) == ["full", "bare", "no_x", "no_y"]


def test_a_later_scored_invocation_replaces_an_earlier_errored_cell():
    first = _part("2026-10-05T09:00:00+05:30", {"bare": {"a": c(0, 0), "b": c(1, 1)}})  # a errored: unscored
    later = _part("2026-10-05T10:00:00+05:30", {"bare": {"a": c(1, 1)}})
    rep = report.ablation_combine([("later", later), ("first", first)], "t")
    assert rep["cells"]["bare"]["a"]["source"] == "later" and rep["cells"]["bare"]["b"]["source"] == "first"


def test_check_evidence_re_derives_a_consolidated_table_and_sees_a_hand_edit(tmp_path, monkeypatch):
    evals = tmp_path / "docs" / "evals"
    parts = [("p1", _part("2026-10-05T09:00:00+05:30", {"full": {"a": c(1, 1)}})),
             ("p2", _part("2026-10-05T10:00:00+05:30", {"no_x": {"a": c(0, 1)}}))]
    for name, rep in parts:
        (evals / name).mkdir(parents=True)
        (evals / name / "report.json").write_text(json.dumps(rep), encoding="utf-8")
    out = report.write_ablation_combined(report.ablation_combine(parts, "t"), evals / "2026-10-05-live-t")
    monkeypatch.setattr(check_evidence, "ROOT", tmp_path)
    monkeypatch.setattr(check_evidence, "EVALS", evals)
    (kind, path, meta), = [x for x in check_evidence.committed() if x[0] == "ablation-combined"]
    fresh = check_evidence.regenerate(kind, meta, tmp_path / "fresh")
    assert check_evidence.differences(path, fresh) == []
    md = out / "report.md"
    md.write_text(md.read_text(encoding="utf-8").replace("cost the most", "cost the least"), encoding="utf-8")
    assert check_evidence.differences(path, fresh) != []
