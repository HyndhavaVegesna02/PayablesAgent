"""The eval report (batch 7, CHG-010a, S4): `report.md` and `report.json` in
`docs/evals/<date>-<mode>-<label>/`.

Three levels, per the brief: did the scenario succeed (end to end), was the
path sound (the trajectory metrics of evals/metrics.py), and which component
broke when it failed (each check's component; the earliest in pipeline order
names the run's). Each scenario runs N times: the report gives the success
rate, the spread (the least and most of a run's checks met) and the worst
run, with tokens and cost. An ERRORED run (the budget guard stopped it, or
rate limits outlasted the backoff) is reported apart and is not counted in
the success rate's denominator. Every figure carries the run metadata it
came from: model, prompt version, config hash, commit and date."""

from __future__ import annotations

import json
import statistics
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evals.runner import RunResult
from evals.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent


def git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
        # Untracked files count (a new scenario or variant), except the reports this writes.
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal", "--", ".",
                                ":(exclude)docs/evals"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
        return head + ("+uncommitted" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def aggregate(scenario: Scenario, runs: list[RunResult]) -> dict[str, Any]:
    scored = [r for r in runs if r.status != "ERRORED"]
    passed = [r for r in scored if r.status == "PASSED"]
    worst = min(scored, key=lambda r: (r.met, r.status == "PASSED"), default=None)
    m = [r.metrics for r in scored if r.metrics]

    def avg(key: str) -> float:
        return _mean([x.get(key, 0) for x in m])

    return {
        "scenario": scenario.name, "title": scenario.title, "passes_when": scenario.passes_when,
        "runs": len(runs), "passed": len(passed), "failed": len(scored) - len(passed),
        "errored": len(runs) - len(scored),
        "success_rate": round(len(passed) / len(scored), 3) if scored else None,
        # trajectory: runs whose path checks all held, of the runs that have any
        "path": [sum(r.path_ok is True for r in scored), sum(r.path_ok is not None for r in scored)],
        "path_failures": [{"run": r.run, "checks": [{"id": c.id, "got": c.got, "want": c.want} for c in r.checks
                                                     if c.level == "trajectory" and not c.ok]}
                          for r in scored if r.path_ok is False][:1],
        "spread": [round(min(r.met for r in scored), 3), round(max(r.met for r in scored), 3)] if scored else None,
        "worst": None if worst is None else {
            "run": worst.run, "status": worst.status, "component": worst.component, "error": worst.error,
            "failed_checks": [{"id": c.id, "component": c.component, "got": c.got, "want": c.want}
                              for c in worst.checks if not c.ok and c.level == "end_to_end"]},
        "components_failed": sorted({r.component for r in scored if r.component}),
        "mean": {k: avg(k) for k in ("ai_calls", "tool_calls", "refused", "loops", "wasted_calls", "retries",
                                       "schema_failures", "invalid_candidates")},
        "escalations": sorted({rule for x in m for rule in x.get("escalations", [])}),
        "tokens_mean": {k: _mean([x.get("tokens", {}).get(k, 0) for x in m]) for k in ("input", "output", "thoughts")},
        "cost_micro_usd": {"mean": avg("cost_micro_usd"), "max": max((x.get("cost_micro_usd", 0) for x in m), default=0)},
    }


def build(meta: dict[str, Any], scenarios: list[Scenario], results: list[RunResult]) -> dict[str, Any]:
    rows = [aggregate(s, [r for r in results if r.scenario == s.name]) for s in scenarios]
    rows = [r for r in rows if r["runs"]]
    scored = [r for r in results if r.status != "ERRORED"]
    return {
        "meta": meta,
        "totals": {
            "scenarios": len(rows), "runs": len(results),
            "passed": sum(r.status == "PASSED" for r in results), "errored": sum(r.status == "ERRORED" for r in results),
            "success_rate": round(sum(r.status == "PASSED" for r in scored) / len(scored), 3) if scored else None,
            "scenarios_all_runs_passed": sum(r["passed"] == r["runs"] for r in rows),
            "path": [sum(r.path_ok is True for r in scored), sum(r.path_ok is not None for r in scored)],
            "ai_calls": sum(r.metrics.get("ai_calls", 0) for r in results),
            "cost_micro_usd": sum(r.metrics.get("cost_micro_usd", 0) for r in results),
        },
        "scenarios": rows,
        "runs": [asdict(r) for r in results],
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def markdown(report: dict[str, Any]) -> str:
    m, t = report["meta"], report["totals"]
    out = [f"# Eval report: {m['label']}", ""]
    if m.get("status") != "COMPLETE":
        out += [f"**{m.get('status')}**: {m.get('stopped_because', '')}. The figures below cover only the runs "
                "that finished.", ""]
    out += [
        "| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario | Variant |",
        "|---|---|---|---|---|---|---|---|",
        f"| {m['mode']} | {m['model']} | {m['prompt_version']} | {m['config_sha256'][:12]} | {m['commit']} | "
        f"{m['date']} | {m['runs_per_scenario']} | {m.get('variant') or 'none'} |",
        "",
    ]
    if m.get("prompt_overrides"):
        out += ["Prompt files swapped in by the variant: " + ", ".join(
            f"`{k}` ← `{v}`" for k, v in m["prompt_overrides"].items()) + ".", ""]
    if m["mode"] == "fixtures":
        out += ["Fixture mode: every model reply is canned (fixtures/ai_replies.json), so runs are deterministic "
                "and the tokens and cost are zero. It shows the harness and the code paths, not the model.", ""]
    out += [
        f"**Totals:** {t['passed']} of {t['runs']} runs passed ({_pct(t['success_rate'])} of the runs that "
        f"finished), {t['errored']} errored; {t['scenarios_all_runs_passed']} of {t['scenarios']} scenarios passed "
        f"every run; path checks held in {t['path'][0]} of the {t['path'][1]} runs that have them; "
        f"{t['ai_calls']} model calls; {t['cost_micro_usd']} micro-USD.",
        "",
    ]
    return "\n".join(out + _scenario_sections(report["scenarios"]))


def _scenario_sections(rows: list[dict[str, Any]], *, source: bool = False) -> list[str]:
    """The scenario table, its failures and path failures, and the column notes. `source` adds a From column
    (a combined report: the report each row came from)."""
    out = [
        "## Scenarios",
        "",
        "| Scenario | " + ("From | " if source else "") + "Success | Path | Spread (checks met) | Worst run "
        "| Model calls | Tool calls | Wasted | Retries | Escalations | Tokens in / out / thoughts | Cost µUSD mean / max |",
        "|---|" + ("---|" if source else "") + "---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        w = r["worst"]
        worst = "n/a" if w is None else ("all end-to-end checks met" if w["status"] == "PASSED" else
                                         f"run {w['run']}: {w['component']}, {len(w['failed_checks'])} failed")
        spread = "n/a" if r["spread"] is None else f"{_pct(r['spread'][0])} – {_pct(r['spread'][1])}"
        tok = r["tokens_mean"]
        errored = f", {r['errored']} errored" if r["errored"] else ""
        success = f"{r['passed']}/{r['runs'] - r['errored']} ({_pct(r['success_rate'])}){errored}"
        path = "no path checks" if not r["path"][1] else f"{r['path'][0]}/{r['path'][1]}"
        out.append(
            f"| {r['title']} | " + (f"`{r['source']}` | " if source else "") +
            f"{success} | {path} | {spread} | {worst} | {r['mean']['ai_calls']} | {r['mean']['tool_calls']} "
            f"| {r['mean']['wasted_calls']} | {r['mean']['retries']} | {', '.join(r['escalations']) or 'none'} "
            f"| {tok['input']:.0f} / {tok['output']:.0f} / {tok['thoughts']:.0f} "
            f"| {r['cost_micro_usd']['mean']:.0f} / {r['cost_micro_usd']['max']} |")
    failures = [r for r in rows if r["worst"] and r["worst"]["status"] != "PASSED"]
    if failures:
        out += ["", "## Failures (the worst run of each scenario that failed)", ""]
        for r in failures:
            w = r["worst"]
            out.append(f"**{r['title']}**, run {w['run']}: broke at **{w['component']}**"
                       + (f" ({w['error']})" if w["error"] else "") + ".")
            for c in w["failed_checks"]:
                out.append(f"- `{c['id']}` ({c['component']}): got `{c['got']}`, wanted `{c['want']}`")
            out.append("")
    path_failures = [r for r in rows if r["path_failures"]]
    if path_failures:
        out += ["", "## Path failures (the first run of each scenario whose path checks failed)", ""]
        for r in path_failures:
            pf = r["path_failures"][0]
            out.append(f"**{r['title']}**, run {pf['run']}"
                       + (": the end result held." if r["passed"] == r["runs"] - r["errored"] else ".") )
            for c in pf["checks"]:
                out.append(f"- `{c['id']}`: got `{c['got']}`, wanted `{c['want']}`")
            out.append("")
    out += ["", "## What each column means", "",
            "- **Success:** runs whose every end-to-end check held, of the runs that finished (ERRORED runs are not "
            "counted). A live run leaves out the checks that pin the fixture AI's own path.",
            "- **Path:** runs whose trajectory checks held (the path taken: steps, escalations), of the runs of a "
            "scenario that has any. A path failure doesn't fail the run's success.",
            "- **Spread:** the least and most share of a scenario's end-to-end checks a run met, across its runs.",
            "- **Worst run:** the run with the fewest checks met, and the component its first failed check (in "
            "pipeline order: sort, extract, validate, reconcile, planner, agent) belongs to.",
            "- **Model calls, tool calls, wasted, retries:** means per run, counted from the run's own trace and job "
            "table (evals/metrics.py). Wasted = refused tool calls + replies that failed the schema + candidates "
            "that failed their checks.",
            "- **Escalations:** the escalation rules any run's trace recorded.", ""]
    return out


# --- one report from several invocations (batch 10, CHG-035) -----------------------------------------------------

SOURCE_FIELDS = ("mode", "model", "prompt_version", "config_sha256", "variant", "commit", "date", "status",
                 "stopped_because", "runs_per_scenario")


def combine(parts: list[tuple[str, dict[str, Any]]], label: str) -> dict[str, Any]:
    """One report from two or more, each given with the folder it came from.
    For every scenario the latest report (by its own date) that finished a
    run of it wins: its row and its runs are this report's, and the row names
    its source. Totals are
    counted from the winning runs; `spent` adds up every invocation's spend,
    the runs that lost included. Nothing here is typed by hand."""
    if len(parts) < 2:
        raise ValueError("combine needs two or more reports")
    parts = sorted(parts, key=lambda p: str(p[1]["meta"]["date"]))  # latest by its own date, not argument order
    rows: dict[str, dict[str, Any]] = {}
    runs: dict[str, list[dict[str, Any]]] = {}
    for source, rep in parts:
        for row in rep["scenarios"]:
            if row["runs"] == row["errored"] and row["scenario"] in rows:
                continue  # every run of it errored here: the earlier finished runs stand
            rows[row["scenario"]] = {**row, "source": source}
            runs[row["scenario"]] = [r for r in rep["runs"] if r["scenario"] == row["scenario"]]
    chosen = [rows[name] for name in sorted(rows)]
    won = [r for name in sorted(runs) for r in runs[name]]
    scored = sum(r["runs"] - r["errored"] for r in chosen)
    passed = sum(r["passed"] for r in chosen)
    sources = [{"report": source, **{k: rep["meta"].get(k) for k in SOURCE_FIELDS},
                "calls": (rep["meta"].get("budget") or {}).get("calls", rep["totals"]["ai_calls"]),
                "micro_usd": (rep["meta"].get("budget") or {}).get("micro_usd", rep["totals"]["cost_micro_usd"])}
               for source, rep in parts]
    return {
        "meta": {"kind": "combined", "label": label, "mode": parts[-1][1]["meta"]["mode"],
                 "model": parts[-1][1]["meta"]["model"], "sources": sources},
        "totals": {
            "scenarios": len(chosen), "runs": sum(r["runs"] for r in chosen), "passed": passed,
            "errored": sum(r["errored"] for r in chosen),
            "success_rate": round(passed / scored, 3) if scored else None,
            "scenarios_all_runs_passed": sum(r["passed"] == r["runs"] for r in chosen),
            "path": [sum(r["path"][0] for r in chosen), sum(r["path"][1] for r in chosen)],
            "ai_calls": sum(r["metrics"].get("ai_calls", 0) for r in won if r.get("metrics")),
            "cost_micro_usd": sum(r["metrics"].get("cost_micro_usd", 0) for r in won if r.get("metrics")),
            "spent": {"calls": sum(s["calls"] for s in sources), "micro_usd": sum(s["micro_usd"] for s in sources)},
        },
        "scenarios": chosen,
    }


def combined_markdown(report: dict[str, Any]) -> str:
    m, t = report["meta"], report["totals"]
    out = [f"# Eval report: {m['label']} (combined)", "",
           f"One report from {len(m['sources'])} invocations, generated by `python -m evals.report combine` from "
           "their report.json files. Each scenario's row is the latest invocation that ran it (the From column); "
           "a scenario run again later replaces its earlier row here, and the earlier one stays in its own report.",
           "", "| Report | Mode | Model | Prompt version | Commit | Date | Status | Runs per scenario | Model calls | "
           "Cost µUSD |", "|---|---|---|---|---|---|---|---|---|---|"]
    for s in m["sources"]:
        status = s["status"] + (f" ({s['stopped_because']})" if s.get("stopped_because") else "")
        out.append(f"| `{s['report']}` | {s['mode']} | {s['model']} | {s['prompt_version']} | {s['commit']} | "
                   f"{s['date']} | {status} | {s['runs_per_scenario']} | {s['calls']} | {s['micro_usd']} |")
    out += ["", f"**Totals:** {t['passed']} of {t['runs']} runs passed ({_pct(t['success_rate'])} of the runs that "
            f"finished), {t['errored']} errored; {t['scenarios_all_runs_passed']} of {t['scenarios']} scenarios passed "
            f"every run; path checks held in {t['path'][0]} of the {t['path'][1]} runs that have them; "
            f"{t['ai_calls']} model calls; {t['cost_micro_usd']} micro-USD in the rows shown, "
            f"{t['spent']['calls']} calls and {t['spent']['micro_usd']} micro-USD spent across the invocations.", ""]
    return "\n".join(out + _scenario_sections(report["scenarios"], source=True))


def write_combined(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(combined_markdown(report), encoding="utf-8")
    return out_dir


def load_parts(folders: list[Path]) -> list[tuple[str, dict[str, Any]]]:
    """(folder name, report) for each report folder, in the order given."""
    return [(f.name, json.loads((f / "report.json").read_text(encoding="utf-8"))) for f in folders]


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="python -m evals.report",
                                description="combine: one report from several report folders, oldest first.")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("combine")
    c.add_argument("folders", type=Path, nargs="+", help="two or more report folders under docs/evals")
    c.add_argument("--label", required=True)
    c.add_argument("--out", type=Path, default=ROOT / "docs" / "evals")
    args = p.parse_args(argv)
    parts = load_parts(args.folders)
    report = combine(parts, args.label)
    last = parts[-1][1]["meta"]
    out = write_combined(report, args.out / f"{str(last['date'])[:10]}-{last['mode']}-{args.label}")
    print(f"combined {len(parts)} reports: {out}")
    return 0



def write(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(markdown(report), encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    raise SystemExit(main())
