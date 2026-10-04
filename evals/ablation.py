"""The harness ablation (TDD Part 1, "Harness comparison"; batch 7, CHG-010a,
S6): the full system against a bare harness on the same model, and against
the full system with one control knocked out at a time.

    python -m evals.ablation --ai fixtures|live [--runs 1] [--harness NAME] [--scenario NAME] [--label X]

Every harness is scored the same way, on each scenario's `outcome` checks:
the business result alone (evals/outcomes.py). Which component earned the
most is the knock-out whose removal costs the most outcome successes.

In fixture mode the canned replies cover only the full system's prompts, so
the bare harness and the no_planner knock-out get a stand-in model that runs
their mechanics (one read, then a final answer that plans nothing). Their rows
are marked "mechanics only" and are left out of the comparison: what they
score needs the live model."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ai.client import Backend, Contents, RawAIResponse
from app.config import AppConfig
from app.trace.tracer import Tracer
from evals import bare, budget, knockouts, metrics, runner
from evals.runner import RunEnv, RunResult, never
from evals.scenario import Scenario

HARNESSES = ("full", "bare", *knockouts.KNOCKOUTS)
MECHANICS_ONLY_IN_FIXTURES = frozenset({"bare", "no_planner"})  # their model calls have no canned reply
# One request timeout for every harness's live calls (CHG-044): the bare harness sends one growing chat
# history, which ran past Gemini's deadline at config.yaml's 60 s; the same longer value for all keeps the
# comparison fair. The product keeps config.yaml's.
TIMEOUT_MS = 180_000
FAIRNESS = (
    "**How the harnesses are compared (D24).** Every harness gets the same inputs: the seeded worked example "
    "and the scenario's emails, uploads and owner actions, in the same order. The bare harness is given them as "
    "text (the seeded state written out, each email's text with its attachments, each owner action as a "
    "sentence) because it has no ingest pipeline; the model is the same. Where an entry is missing a field the "
    "owner must fill, every harness's owner fills it with the same value from the scenario: the full system and "
    "the knock-outs type it into the field the page marks, and the bare harness hears it as a sentence, so no "
    "harness gets more of the document than another (PO, batch 10). The bare harness's every call, and the "
    "no_planner knock-out's plan call, is at medium thinking, the level of the full system's extract and "
    "exception work; the full system uses config.yaml's level per job. Live, every harness's calls share one "
    f"request timeout, {TIMEOUT_MS // 1000} seconds, long enough for the bare harness's growing history. Only the "
    "harness differs. Every harness "
    "is scored on the same `outcome` checks: the business result in its own database (and the week's plan), "
    "never how it got there.")


class MechanicsModel:
    """Fixture mode's stand-in for the replies no fixture has: the bare
    harness's steps and the no_planner knock-out's plan. It runs their
    mechanics and plans nothing; the rows it touches are not compared."""

    def __init__(self, inner: Backend) -> None:
        self.inner = inner

    def generate(self, *, model: str, system: str, contents: Contents, thinking: str,
                 json_schema: dict[str, Any] | None) -> RawAIResponse:
        title = (json_schema or {}).get("title", "")
        text = contents if isinstance(contents, str) else "\n".join(c for c in contents if isinstance(c, str))
        if title == "BareStep":
            step = ({"notes": "fixture stand-in: reads the bills once", "tool": {"name": "list_bills", "args": {}}}
                    if "Step 1:" not in text else
                    {"notes": "fixture stand-in: plans nothing",
                     "final": {"lowest_balance_text": "Rs.0", "decisions": [], "summary": "fixture stand-in"}})
            return RawAIResponse(json.dumps(step), 0, 0, 0)
        if title == "ModelPlan":
            return RawAIResponse(json.dumps({"lowest_balance_text": "Rs.0", "lowest_on": "2026-10-12",
                                             "decisions": []}), 0, 0, 0)
        return self.inner.generate(model=model, system=system, contents=contents, thinking=thinking,
                                   json_schema=json_schema)


def run_harness(name: str, scenario: Scenario, backend: Backend, app_config: AppConfig, run: int, *,
                should_stop: Callable[[], str | None] = never,
                keep: Path | None = None) -> tuple[RunResult, list[str]]:
    """One run of one scenario under one harness; the result and the seams it patched. With `keep`, the
    run's traces are copied there."""
    if name == "full":
        return runner.run_once(scenario, backend, app_config, run, should_stop=should_stop,
                               inspect=metrics.inspect, keep=keep), []
    if name == "bare":
        return bare.run_once(scenario, backend, app_config, run, should_stop=should_stop, keep=keep), []
    binding = knockouts.Binding()

    def bind(env: RunEnv) -> None:
        binding.backend, binding.app_config = backend, env.app_config
        binding.tracer = Tracer(f"knockout-{name}", env.settings.trace_dir, env.clock)

    with knockouts.applied(name, binding) as seams:
        result = runner.run_once(scenario, backend, app_config, run, should_stop=should_stop,
                                 inspect=metrics.inspect, setup=bind, keep=keep)
    return result, seams


def build(meta: dict[str, Any], harnesses: list[str], scenarios: list[Scenario],
          results: dict[str, list[RunResult]], seams: dict[str, list[str]]) -> dict[str, Any]:
    fixtures = meta["mode"] == "fixtures"

    def rate(rs: list[RunResult]) -> float | None:
        scored = [r for r in rs if r.status != "ERRORED"]
        return round(sum(r.outcome_ok for r in scored) / len(scored), 3) if scored else None

    per = {}
    for h in harnesses:
        rs = results.get(h, [])
        per[h] = {
            "mechanics_only": fixtures and h in MECHANICS_ONLY_IN_FIXTURES,
            "seams": seams.get(h, []),
            "runs": len(rs), "errored": sum(r.status == "ERRORED" for r in rs),
            "outcome_success_rate": rate(rs),
            "by_scenario": {s.name: {"met": sum(r.outcome_ok for r in rs if r.scenario == s.name),
                                     "scored": sum(r.status != "ERRORED" for r in rs if r.scenario == s.name)}
                            for s in scenarios},
            "ai_calls": sum(r.metrics.get("ai_calls", 0) for r in rs),
            "cost_micro_usd": sum(r.metrics.get("cost_micro_usd", 0) for r in rs),
        }
    full = per.get("full", {}).get("outcome_success_rate")
    drops = {h: round(full - p["outcome_success_rate"], 3) for h, p in per.items()
             if h in knockouts.KNOCKOUTS and not p["mechanics_only"] and full is not None
             and p["outcome_success_rate"] is not None}
    top = max(drops.values(), default=None)
    return {"meta": meta, "harnesses": per, "drops": drops,
            "earned_most": sorted(h for h, d in drops.items() if d == top) if top is not None and top > 0 else [],
            "runs": {h: [{"scenario": r.scenario, "run": r.run, "status": r.status, "outcome_ok": r.outcome_ok,
                          "outcomes": r.outcomes, "error": r.error} for r in rs] for h, rs in results.items()}}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def markdown(report: dict[str, Any], scenarios: list[Scenario]) -> str:
    m, per = report["meta"], report["harnesses"]
    out = [f"# Harness ablation: {m['label']}", ""]
    if m.get("status") != "COMPLETE":
        out += [f"**{m.get('status')}**: {m.get('stopped_because', '')}. The figures below cover only the runs "
                "that finished.", ""]
    out += [FAIRNESS, "",
            "| Mode | Model | Prompt version | Config | Commit | Date | Runs per scenario |",
            "|---|---|---|---|---|---|---|",
            f"| {m['mode']} | {m['model']} | {m['prompt_version']} | {m['config_sha256'][:12]} | {m['commit']} "
            f"| {m['date']} | {m['runs_per_scenario']} |", ""]
    if m["mode"] == "fixtures":
        out += ["Fixture mode: every model reply is canned, so the full system and the knock-outs that keep its "
                "prompts are deterministic, and tokens and cost are zero. The rows marked *mechanics only* ran "
                "on a stand-in that plans nothing; they show the harness runs, not what it scores, and are left "
                "out of the comparison. The live run (`--ai live --yes-spend`) scores them.", ""]
    names = list(per)
    out += ["## Outcome checks met, by scenario", "", "| Scenario | " + " | ".join(names) + " |",
            "|---|" + "---|" * len(names)]
    for s in scenarios:
        cells = []
        for h in names:
            c = per[h]["by_scenario"].get(s.name, {"met": 0, "scored": 0})
            cells.append("—" if not c["scored"] else f"{c['met']}/{c['scored']}"
                         + (" *mechanics only*" if per[h]["mechanics_only"] else ""))
        out.append(f"| {s.title} | " + " | ".join(cells) + " |")
    out.append("| **Outcome success** | " + " | ".join(
        _pct(per[h]["outcome_success_rate"]) + (" *mechanics only*" if per[h]["mechanics_only"] else "")
        for h in names) + " |")
    out.append("| Model calls | " + " | ".join(str(per[h]["ai_calls"]) for h in names) + " |")
    out.append("| Cost µUSD | " + " | ".join(str(per[h]["cost_micro_usd"]) for h in names) + " |")
    out += ["", "## Which component earned the most", ""]
    if report["earned_most"]:
        d = report["drops"][report["earned_most"][0]]
        out.append(f"Knocking out **{', '.join(report['earned_most'])}** cost the most: outcome success fell by "
                   f"{d * 100:.0f} points from the full system's {_pct(per['full']['outcome_success_rate'])}.")
    else:
        out.append("No knock-out compared here lowered outcome success.")
    out += ["", "| Knock-out | Drop in outcome success (points) |", "|---|---|"]
    out += [f"| {h} | {d * 100:.0f} |" for h, d in sorted(report["drops"].items(), key=lambda kv: -kv[1])]
    out += ["", "## What each knock-out patched", "",
            "Each is a context manager over named seams (evals/knockouts.py), restored after every run; app code "
            "has no ablation flag.", ""]
    for h in names:
        if per[h]["seams"]:
            out.append(f"- **{h}:** " + ", ".join(f"`{s}`" for s in per[h]["seams"]))
    if "no_rule_checks" in per:
        out.append("- **no_rule_checks** leaves on the checks that decide whether a record can be read at all: "
                   + ", ".join(knockouts.RULE_CHECKS_LEFT_ON) + ".")
    out += ["- **bare:** evals/bare.py: one growing chat history, every tool (write tools included) on its own "
            f"database, no checks, no case file, no escalation, no planner, a cap of {bare.MAX_STEPS} steps.", ""]
    return "\n".join(out)


def write(report: dict[str, Any], scenarios: list[Scenario], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(markdown(report, scenarios), encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    import argparse

    from app.ai.fixture_backend import FixtureBackend
    from app.clock import SystemClock
    from evals import report as eval_report
    from evals import scenario as scenario_files

    p = argparse.ArgumentParser(prog="python -m evals.ablation", description="Compare the harnesses.")
    p.add_argument("--ai", choices=["fixtures", "live"], required=True)
    p.add_argument("--runs", type=int, default=1, help="runs per scenario per harness (default 1)")
    p.add_argument("--harness", action="append", choices=HARNESSES, help="only this harness (repeatable)")
    p.add_argument("--scenario", action="append", help="only this scenario (repeatable)")
    p.add_argument("--label", default="ablation")
    p.add_argument("--out", type=Path, default=runner.ROOT / "docs" / "evals")
    p.add_argument("--yes-spend", action="store_true", help="required with --ai live")
    p.add_argument("--keep-traces", action="store_true",
                   help="copy each run's traces next to the report (always on with --ai live)")
    budget.add_max_usd(p)
    args = p.parse_args(argv)

    config, config_hash = runner.load_config()
    default = scenario_files.live_names() if args.ai == "live" else scenario_files.names()  # fixture-only stay offline
    chosen = [scenario_files.load(n) for n in (args.scenario or default)]
    harnesses = args.harness or list(HARNESSES)
    today = SystemClock().now()
    out_dir = args.out / f"{today.date().isoformat()}-{args.ai}-{args.label}"
    keep_traces = args.keep_traces or args.ai == "live"  # a live run's traces are kept (CHG-047)
    guard = None
    should_stop: Callable[[], str | None] = never
    if args.ai == "live":
        guard = budget.live_backend(config, confirmed=args.yes_spend,  # one guard for the whole invocation
                                    max_micro_usd=args.max_micro_usd, timeout_ms=TIMEOUT_MS)
        should_stop = guard.should_stop

    def backend() -> Backend:
        return guard if guard is not None else MechanicsModel(FixtureBackend())

    results: dict[str, list[RunResult]] = {h: [] for h in harnesses}
    seams: dict[str, list[str]] = {}
    stopped = None
    for h in harnesses:
        for s in chosen:
            for i in range(1, args.runs + 1):
                stopped = stopped or should_stop()
                if stopped:
                    break
                keep = out_dir / "traces" / f"{h}-{s.name}-run{i}" if keep_traces else None
                r, seams[h] = run_harness(h, s, backend(), config, i, should_stop=should_stop, keep=keep)
                results[h].append(r)
                print(f"{h:15} {'met' if r.outcome_ok else r.status:8} {s.name} run {i}", flush=True)
    meta = {"label": args.label, "mode": args.ai, "model": config.model.id, "prompt_version": config.prompts.version,
            "config_sha256": config_hash, "commit": eval_report.git_commit(),
            "date": today.isoformat(timespec="seconds"), "runs_per_scenario": args.runs,
            "status": "COMPLETE" if stopped is None else "ABORTED", "stopped_because": stopped,
            "budget": guard.summary() if guard else None}
    built = build(meta, harnesses, chosen, results, seams)
    out_dir = write(built, chosen, out_dir)
    print(f"report: {out_dir}")
    return 0 if stopped is None else 1  # an ABORTED comparison is not a result


if __name__ == "__main__":
    raise SystemExit(main())
