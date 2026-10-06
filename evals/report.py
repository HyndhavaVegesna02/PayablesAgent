"""The eval report (batch 7, CHG-010a, S4): `report.md` and `report.json` in
`docs/evals/raw-runs/<date>-<mode>-<label>/` (evals/layout.py).

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
import posixpath
import re
import statistics
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evals import layout
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
    out += [f"**Totals:** {_totals(t)}; {t['ai_calls']} model calls; {t['cost_micro_usd']} micro-USD.", ""]
    return "\n".join(out + _scenario_sections(report["scenarios"]))


def _scenario_sections(rows: list[dict[str, Any]], *, source: bool = False, folder: str | None = None) -> list[str]:
    """The scenario table, its failures and path failures, and the column notes. `source` adds a From column
    (a combined report: the report each row came from, linked from the page's `folder`)."""
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
            f"| {r['title']} | " + (f"{_link(r['source'], folder)} | " if source else "") +
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


# --- one report from several invocations (batch 10, CHG-035; CHG-055) -------------------------------------------

SOURCE_FIELDS = ("mode", "model", "prompt_version", "config_sha256", "variant", "commit", "date", "status",
                 "stopped_because", "runs_per_scenario")


def stopped_reason(meta: dict[str, Any]) -> str | None:
    """Why an invocation stopped, as it recorded it: its own reason, or the budget guard's (the guard can stop
    the last run of an invocation whose header still says COMPLETE)."""
    return meta.get("stopped_because") or (meta.get("budget") or {}).get("stopped")


def plain_status(status: str | None, stopped: str | None) -> str:
    """An invocation's status in plain words, true to the reason it recorded."""
    if not stopped:
        return "Complete" if status == "COMPLETE" else str(status)
    if stopped.startswith(("cost cap reached", "call cap reached")):
        return f"Stopped by our budget guard ({stopped.split(' reached')[0]})"
    if stopped.startswith("spend cap"):
        return "Stopped: Google's project spending cap (429)"
    if stopped.startswith("credits depleted"):
        return "Stopped: Google's prepaid credits ran out (402)"
    backoffs = re.search(r"outlasted (\d+) backoffs", stopped)
    if stopped.startswith("rate limited") and backoffs:
        return f"Stopped: Google kept refusing (429) after {backoffs.group(1)} backoffs"
    return f"Stopped: {stopped}"


def _link(source: str, folder: str | None) -> str:
    """A source's name, linked to its report from the page at `folder` (both under docs/evals)."""
    name = f"`{posixpath.basename(source)}`"
    return name if folder is None else f"[{name}]({posixpath.relpath(source, folder)}/report.md)"


def _sources(parts: list[tuple[str, dict[str, Any]]], used: dict[str, int],
             **extra: Callable[[dict[str, Any]], Any]) -> list[dict[str, Any]]:
    """Each invocation's metadata, why it stopped, and how many of its finished runs the page uses."""
    out = []
    for source, rep in parts:
        budget, totals = rep["meta"].get("budget") or {}, rep.get("totals") or {}
        out.append({"report": source, **{k: rep["meta"].get(k) for k in SOURCE_FIELDS},
                    **{k: f(rep) for k, f in extra.items()},
                    "stopped": stopped_reason(rep["meta"]), "runs_used": used.get(source, 0),
                    "calls": budget.get("calls", totals.get("ai_calls", 0)),
                    "micro_usd": budget.get("micro_usd", totals.get("cost_micro_usd", 0))})
    return out


def _stopped_sentence(sources: list[dict[str, Any]], rest: str) -> list[str]:
    if not any(s["stopped"] for s in sources):
        return []
    return [f"A stopped invocation's finished runs are valid, and they are counted here; {rest} The source "
            "reports keep each stop's reason as it was recorded.", ""]


def combine(parts: list[tuple[str, dict[str, Any]]], label: str, folder: str | None = None) -> dict[str, Any]:
    """One report from two or more, each given with its folder (its path under docs/evals).
    For every scenario the latest report (by its own date) that finished a
    run of it wins: its row and its runs are this report's, and the row names
    its source. Every report's row of a scenario is kept in `coverage`, so
    the page can say what a replaced row showed. Totals are
    counted from the winning runs; `spent` adds up every invocation's spend,
    the runs that lost included. `folder` is the page's own folder under
    docs/evals, for its links. Nothing here is typed by hand."""
    if len(parts) < 2:
        raise ValueError("combine needs two or more reports")
    parts = sorted(parts, key=lambda p: str(p[1]["meta"]["date"]))  # latest by its own date, not argument order
    rows: dict[str, dict[str, Any]] = {}
    runs: dict[str, list[dict[str, Any]]] = {}
    history: dict[str, list[dict[str, Any]]] = {}
    planned: dict[str, int] = {}
    for source, rep in parts:
        for row in rep["scenarios"]:
            history.setdefault(row["scenario"], []).append(
                {"source": source, "passed": row["passed"], "finished": row["runs"] - row["errored"],
                 "errored": row["errored"]})
            if row["runs"] == row["errored"] and row["scenario"] in rows:
                continue  # every run of it errored here: the earlier finished runs stand
            rows[row["scenario"]] = {**row, "source": source}
            runs[row["scenario"]] = [r for r in rep["runs"] if r["scenario"] == row["scenario"]]
            planned[row["scenario"]] = rep["meta"].get("runs_per_scenario") or row["runs"]
    chosen = [rows[name] for name in sorted(rows)]
    won = [r for name in sorted(runs) for r in runs[name]]
    scored = sum(r["runs"] - r["errored"] for r in chosen)
    passed = sum(r["passed"] for r in chosen)
    used: dict[str, int] = {}
    for r in chosen:
        used[r["source"]] = used.get(r["source"], 0) + r["runs"] - r["errored"]
    sources = _sources(parts, used)
    return {
        "meta": {"kind": "combined", "label": label, "mode": parts[-1][1]["meta"]["mode"],
                 "model": parts[-1][1]["meta"]["model"], "folder": folder, "sources": sources},
        "coverage": {"planned": sum(planned.values()), "scored": scored,
                     "runs_per_scenario": sorted(set(planned.values())),
                     "replaced": {name: history[name] for name in sorted(history) if len(history[name]) > 1}},
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


# --- one ablation table from several invocations (CHG-048; CHG-055) --------------------------------


def _rate(met: int, scored: int) -> float | None:
    return round(met / scored, 3) if scored else None


def ablation_combine(parts: list[tuple[str, dict[str, Any]]], label: str,
                     folder: str | None = None) -> dict[str, Any]:
    """One harness-by-scenario table from ablation report.json files, each
    given with its folder. For each harness and scenario, the latest
    invocation (by its own date) that scored a run of it wins, as in
    `combine`. A knock-out's drop is paired: the full system's success on the
    scenarios that knock-out was scored on, less the knock-out's. A drop is
    measured only for a harness scored on more than half the scenarios; the
    others are `not_measured`, and none of them can have earned the most.
    Nothing here is typed by hand."""
    if not parts:
        raise ValueError("ablation-combine needs at least one ablation report")
    parts = sorted(parts, key=lambda p: str(p[1]["meta"]["date"]))
    cells: dict[str, dict[str, dict[str, Any]]] = {}
    for source, rep in parts:
        for h, per in rep["harnesses"].items():
            if per.get("mechanics_only") or per.get("context_only"):
                continue  # a fixture stand-in plans nothing, or canned replies can't show the effect: not compared
            for s, c in per["by_scenario"].items():
                if c["scored"] or s not in cells.get(h, {}):
                    cells.setdefault(h, {})[s] = {**c, "source": source}
    order = ["full", "bare", *sorted(h for h in cells if h not in ("full", "bare"))]
    harnesses = [h for h in order if h in cells]
    scenarios = sorted({s for h in cells for s in cells[h]})

    def success(h: str, only: set[str] | None = None) -> float | None:
        picked = [c for s, c in cells[h].items() if only is None or s in only]
        return _rate(sum(c["met"] for c in picked), sum(c["scored"] for c in picked))

    per: dict[str, Any] = {}
    for h in harnesses:
        rates = [_rate(c["met"], c["scored"]) for c in cells[h].values() if c["scored"]]
        per[h] = {"met": sum(c["met"] for c in cells[h].values()), "scored": sum(c["scored"] for c in cells[h].values()),
                  "success": success(h), "spread": [min(rates), max(rates)] if rates else None,
                  "scenarios_scored": sorted(s for s, c in cells[h].items() if c["scored"]),
                  "runs_per_cell": {s: c["scored"] for s, c in sorted(cells[h].items()) if c["scored"]}}
    drops: dict[str, float] = {}
    paired: dict[str, int] = {}
    lost: dict[str, list[str]] = {}
    not_measured: dict[str, int] = {}
    if "full" in cells:
        for h in harnesses:
            if h == "full":
                continue
            if 2 * len(per[h]["scenarios_scored"]) <= len(scenarios):
                not_measured[h] = len(per[h]["scenarios_scored"])  # half the scenarios or fewer: no drop shown
                continue
            both = set(per[h]["scenarios_scored"]) & set(per["full"]["scenarios_scored"])
            full, mine = success("full", both), success(h, both)
            if full is not None and mine is not None:
                drops[h], paired[h] = round(full - mine, 3), len(both)
                lost[h] = sorted(s for s in both if (success(h, {s}) or 0) < (success("full", {s}) or 0))
    knock = {h: d for h, d in drops.items() if h != "bare"}
    top = max(knock.values(), default=None)
    used: dict[str, int] = {}
    for h in harnesses:
        for c in cells[h].values():
            used[c["source"]] = used.get(c["source"], 0) + c["scored"]
    sources = _sources(parts, used, harnesses=lambda rep: sorted(rep["harnesses"]))
    return {
        "meta": {"kind": "ablation-combined", "label": label, "mode": parts[-1][1]["meta"]["mode"],
                 "model": parts[-1][1]["meta"]["model"], "folder": folder, "sources": sources},
        "harnesses": per, "scenarios": scenarios,
        "cells": {h: {s: cells[h].get(s) for s in scenarios} for h in harnesses},
        "full_vs_bare": drops.get("bare"), "drops": knock, "paired_on": paired, "lost": lost,
        "not_measured": not_measured,
        "earned_most": sorted(h for h, d in knock.items() if d == top) if top is not None and top > 0 else [],
        "spent": {"calls": sum(s["calls"] for s in sources), "micro_usd": sum(s["micro_usd"] for s in sources)},
    }


def _runs_per_cell(cells: dict[str, int]) -> str:
    """'3 (2 on 11-shortfall-week)': the usual count of runs in a harness's cells, and the cells that differ."""
    if not cells:
        return "n/a"
    counts = list(cells.values())
    usual = max(set(counts), key=lambda k: (counts.count(k), k))
    odd = [f"{k} on {s}" for s, k in cells.items() if k != usual]
    return str(usual) + (f" ({', '.join(odd)})" if odd else "")


def ablation_combined_markdown(rep: dict[str, Any]) -> str:
    m, hs, n = rep["meta"], list(rep["harnesses"]), len(rep["scenarios"])
    folder, measured = m.get("folder"), "not measured live" if m["mode"] == "live" else "not measured"

    def pts(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.0f}"

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.0f}%"

    out = [f"# Harness ablation: {m['label']} (consolidated)", ""]
    if rep["full_vs_bare"] is not None:
        out += [f"**Headline:** the harness itself, the full system against the bare harness on the same model, "
                f"paired on the {rep['paired_on']['bare']} scenarios both scored: {pts(rep['full_vs_bare'])} points "
                "of outcome success.", ""]
    out += [f"One table from {len(m['sources'])} ablation invocations, generated by `python -m evals.report "
            "ablation-combine` from their report.json files. For each harness and scenario, the latest invocation, "
            "by date, that scored a run of it fills the cell. A knock-out's drop is paired: the full system's success "
            "on the scenarios that knock-out was scored on, less the knock-out's own. A drop is shown only for a "
            f"harness scored on more than half the {n} scenarios.", "",
            "| Invocation | Harnesses | Mode | Model | Prompt version | Commit | Date | Status | Runs per scenario "
            "| Runs used here | Calls | µUSD |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in m["sources"]:
        out.append(f"| {_link(s['report'], folder)} | {', '.join(s['harnesses'])} | {s.get('mode')} | "
                   f"{s.get('model')} | {s.get('prompt_version')} | {s.get('commit')} | {s.get('date')} | "
                   f"{plain_status(s.get('status'), s['stopped'])} | {s.get('runs_per_scenario')} | "
                   f"{s['runs_used']} | {s['calls']} | {s['micro_usd']} |")
    out += [""]
    gaps = [h for h in hs if len(rep["harnesses"][h]["scenarios_scored"]) < n]
    out += _stopped_sentence(m["sources"], "the runs it didn't reach ran in a later invocation." if not gaps else
                             "the runs it didn't reach ran in a later invocation where one followed, and a — cell "
                             f"below is a run no invocation reached ({', '.join(gaps)}).")
    out += ["## Coverage", "", "| Harness | Scenarios scored | Runs per cell | Success | Paired drop (points) |",
            "|---|---|---|---|---|"]
    for h in hs:
        x = rep["harnesses"][h]
        drop = ("—" if h == "full" else f"{measured} ({rep['not_measured'][h]}/{n} scenarios)"
                if h in rep["not_measured"] else pts(rep["full_vs_bare"] if h == "bare" else rep["drops"].get(h)))
        out.append(f"| {h} | {len(x['scenarios_scored'])}/{n} | {_runs_per_cell(x['runs_per_cell'])} | "
                   f"{pct(x['success'])} | {drop} |")
    out += ["", "## Outcome checks met, by scenario", "", "| Scenario | " + " | ".join(hs) + " |",
            "|---|" + "---|" * len(hs)]
    for sc in rep["scenarios"]:
        row = []
        for h in hs:
            c = rep["cells"][h].get(sc)
            row.append("—" if not c or not c["scored"] else f"{c['met']}/{c['scored']}")
        out.append(f"| {sc} | " + " | ".join(row) + " |")
    out.append("| **Success** | " + " | ".join(pct(rep["harnesses"][h]["success"]) for h in hs) + " |")
    out.append("| Spread across scenarios | " + " | ".join(
        "n/a" if rep["harnesses"][h]["spread"] is None else
        f"{rep['harnesses'][h]['spread'][0] * 100:.0f}% – {rep['harnesses'][h]['spread'][1] * 100:.0f}%"
        for h in hs) + " |")
    out += ["", "## What each component is worth", "",
            f"- **The harness (full against bare), paired on the scenarios both scored:** {pts(rep['full_vs_bare'])} "
            "points of outcome success.", "",
            "| Knock-out | Drop in outcome success (points, paired) | Scenarios it lost |", "|---|---|---|"]
    out += [f"| {h} | {pts(d)} | {', '.join(rep['lost'][h]) or 'none'} |"
            for h, d in sorted(rep["drops"].items(), key=lambda kv: (-kv[1], kv[0]))]
    out += [f"| {h} | {measured} ({k}/{n} scenarios) | n/a |" for h, k in sorted(rep["not_measured"].items())
            if h != "bare"]
    out += ["", "## Which component earned the most", ""]
    top = rep["earned_most"]
    if top:
        out.append(f"Knocking out **{', '.join(top)}** cost the most: {pts(rep['drops'][top[0]])} points.")
        if {k for h in top for k in rep["harnesses"][h]["runs_per_cell"].values()} == {1}:
            out.append(f"{'It' if len(top) == 1 else 'Each'} ran once per scenario, so {pts(rep['drops'][top[0]])} "
                       "points is " + "; ".join(
                           f"{len(rep['lost'][h])} scenario{'' if len(rep['lost'][h]) == 1 else 's'} of the "
                           f"{rep['paired_on'][h]} {h} was paired on ({', '.join(rep['lost'][h])})" for h in top)
                       + ".")
    else:
        out.append("No knock-out compared here lowered outcome success.")
    if [h for h in rep["not_measured"] if h != "bare"]:
        out.append(f"Left out: {', '.join(h for h in sorted(rep['not_measured']) if h != 'bare')}, scored on half "
                   "the scenarios or fewer.")
    if folder is not None and m["mode"] == "live":
        out.append(f"[The offline ablation]({posixpath.relpath(layout.OFFLINE_ABLATION, folder)}/report.md) runs "
                   "every harness on every scenario, in fixture mode: it shows the code paths, not the model.")
    out += ["", f"Spent across the invocations: {rep['spent']['calls']} calls, {rep['spent']['micro_usd']} µUSD.", ""]
    return "\n".join(out)


def write_ablation_combined(rep: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(rep, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(ablation_combined_markdown(rep), encoding="utf-8")
    return out_dir


def _results(h: dict[str, Any]) -> str:
    """One invocation's result on a scenario: '4/5', '0/5, 1 errored', or 'no run finished (1 errored)'."""
    if not h["finished"]:
        return f"no run finished ({h['errored']} errored)"
    return f"{h['passed']}/{h['finished']}" + (f", {h['errored']} errored" if h["errored"] else "")


def coverage_line(report: dict[str, Any]) -> str:
    """Runs scored of those planned, the invocations and their commits, and every scenario whose row a later
    invocation replaced, with what each earlier invocation showed."""
    m, c = report["meta"], report["coverage"]
    commits = [s["commit"] for s in m["sources"]]
    per = (f" ({report['totals']['scenarios']} scenarios × {c['runs_per_scenario'][0]} runs)"
           if len(c["runs_per_scenario"]) == 1 else "")
    line = (f"**Coverage:** {c['scored']} of {c['planned']} planned runs scored{per}, from {len(m['sources'])} "
            f"invocations at commits {', '.join(commits[:-1])} and {commits[-1]}.")
    if not c["replaced"]:
        return line + " No scenario's row was replaced by a later invocation."
    told = []
    for name, h in c["replaced"].items():
        steps = [f"{_results(x)} in `{posixpath.basename(x['source'])}`" for x in h]
        told.append(f"{name}: " + ", ".join(steps[:-1]) + f", then {steps[-1]}")
    return line + " Scenarios a later invocation ran again, with every result: " + "; ".join(told) + "."


def _totals(t: dict[str, Any]) -> str:
    """The run totals over one denominator: the runs that finished."""
    return (f"{t['passed']} of {t['runs'] - t['errored']} finished runs passed ({_pct(t['success_rate'])}), "
            f"{t['errored']} errored; {t['scenarios_all_runs_passed']} of {t['scenarios']} scenarios passed every "
            f"run; path checks held in {t['path'][0]} of the {t['path'][1]} runs that have them")


def combined_markdown(report: dict[str, Any]) -> str:
    m, t, c = report["meta"], report["totals"], report["coverage"]
    folder = m.get("folder")
    out = [f"# Eval report: {m['label']} (combined)", "", coverage_line(report), "",
           f"**Totals:** {_totals(t)}; {t['ai_calls']} model calls; {t['cost_micro_usd']} micro-USD in the rows "
           f"shown, {t['spent']['calls']} calls and {t['spent']['micro_usd']} micro-USD spent across the "
           "invocations.", "",
           f"One report from {len(m['sources'])} invocations, generated by `python -m evals.report combine` from "
           "their report.json files. Each scenario's row is the latest invocation, by date, that finished a run of "
           "it (the From column). A later invocation whose runs of a scenario all errored leaves the earlier row in "
           "place; an earlier row that was replaced stays in its own report.",
           "", "| Report | Mode | Model | Prompt version | Commit | Date | Status | Runs per scenario | Runs used here "
           "| Model calls | Cost µUSD |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in m["sources"]:
        out.append(f"| {_link(s['report'], folder)} | {s['mode']} | {s['model']} | {s['prompt_version']} | "
                   f"{s['commit']} | {s['date']} | {plain_status(s['status'], s['stopped'])} | "
                   f"{s['runs_per_scenario']} | {s['runs_used']} | {s['calls']} | {s['micro_usd']} |")
    out += [""] + _stopped_sentence(m["sources"], "the runs it didn't reach ran in a later invocation." if
                                    c["scored"] >= c["planned"] else
                                    f"{c['planned'] - c['scored']} planned runs no invocation finished.")
    return "\n".join(out + _scenario_sections(report["scenarios"], source=True, folder=folder))


def write_combined(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(combined_markdown(report), encoding="utf-8")
    return out_dir


def load_parts(folders: list[Path], evals: Path = layout.EVALS) -> list[tuple[str, dict[str, Any]]]:
    """(the folder's path under docs/evals, its report) for each report folder, in the order given."""
    return [(layout.under(f, evals), json.loads((f / "report.json").read_text(encoding="utf-8"))) for f in folders]


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="python -m evals.report",
                                description="combine: one report from two or more suite report folders; "
                                            "ablation-combine: one harness-by-scenario table from ablation report "
                                            "folders (each ordered by their own dates).")
    sub = p.add_subparsers(dest="command", required=True)
    for name, helptext in (("combine", "two or more suite report folders, e.g. under docs/evals/raw-runs"),
                           ("ablation-combine", "one or more ablation report folders, e.g. under docs/evals/raw-runs")):
        c = sub.add_parser(name)
        c.add_argument("folders", type=Path, nargs="+", help=helptext)
        c.add_argument("--label", required=True)
        c.add_argument("--out", type=Path, required=True,
                       help="the page's own folder, e.g. docs/evals/1-eval-report/live-11x5")
    args = p.parse_args(argv)
    parts = load_parts(args.folders)
    folder = layout.under(args.out)
    if args.command == "ablation-combine":
        out = write_ablation_combined(ablation_combine(parts, args.label, folder), args.out)
    else:
        out = write_combined(combine(parts, args.label, folder), args.out)
    print(f"combined {len(parts)} reports: {out}")
    return 0



def write(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(markdown(report), encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    raise SystemExit(main())
