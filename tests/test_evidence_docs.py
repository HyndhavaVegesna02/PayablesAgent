"""The evidence documents (batch 7, CHG-010c) say only what the code does:
their generated tables and traces are regenerated and compared, the README's
example runs as written, every path they cite exists, and no hand-written
page types a result figure (D25: figures live in generated reports, which
name their commit)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "docs" / "evals"
# The eval READMEs quote headline figures, each one read from its report.json by `quoted()` below (CHG-055).
EVAL_READMES = [EVALS / "README.md", *sorted(EVALS.glob("[0-9]-*/README.md")), EVALS / "raw-runs" / "README.md"]
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "docs" / "traces" / "README.md"]


def test_the_permission_model_tables_are_the_codes_own():
    from scripts import make_docs

    text = make_docs.PAGE.read_text(encoding="utf-8")
    assert make_docs.refreshed(text) == text, "run: uv run python scripts/make_docs.py"
    assert "| POST | `/plans/{run_id}/approve` | owner |" in text and "| POST | `/uploads` | owner, helper |" in text


def test_the_curated_traces_are_what_the_code_writes_today():
    from scripts import make_traces

    for name, text in make_traces.build().items():
        assert (make_traces.OUT / name).read_text(encoding="utf-8") == text, "run: uv run python scripts/make_traces.py"


def test_the_traces_show_the_control_points_their_walkthrough_names():
    import json

    def line(name, n):
        return json.loads((ROOT / "docs" / "traces" / name).read_text(encoding="utf-8").splitlines()[n - 1])

    assert line("success.jsonl", 19)["tool"] == "apply_final"
    assert line("success.jsonl", 32)["escalation_rule"] == "max_validation_failures"
    assert line("success.jsonl", 45)["escalation_rule"] == "max_steps"
    assert line("failure.jsonl", 18)["escalation_rule"] == "max_steps"
    assert line("failure.jsonl", 19)["thinking"] == "high"
    assert line("failure.jsonl", 20)["tool"] == "apply_final"
    assert line("failure.jsonl", 36)["result"] == "run over at high: ask_owner"


def test_the_official_live_traces_are_the_reports_own_and_show_what_their_walkthrough_says():
    """CHG-047: the live pilot's job 11 is the official failure, the AFTER's job 11 the official success."""
    import json

    pairs = {"live-failure.jsonl": "live-pilot-before", "live-success.jsonl": "live-pilot-after"}
    for name, report in pairs.items():
        source = EVALS / "3-improvement-and-regression" / report / "traces" / "07-missed-alert-causes-drift-run1" / \
            "2026-10-15"
        assert (ROOT / "docs" / "traces" / name).read_bytes() == (source / "job-11-attempt-1.jsonl").read_bytes()

    def line(name, n):
        return json.loads((ROOT / "docs" / "traces" / name).read_text(encoding="utf-8").splitlines()[n - 1])

    assert line("live-failure.jsonl", 5)["result"].startswith("refused: ('account',)")
    assert line("live-failure.jsonl", 11)["result"].startswith("candidate 2: INVALID")
    assert (line("live-failure.jsonl", 13)["tool"], line("live-failure.jsonl", 13)["result"]) == (
        "apply_final", "nothing to write")
    assert line("live-success.jsonl", 7)["result"] == "candidate 2: VALID, every rule check passed"
    assert line("live-success.jsonl", 9)["result"] == "candidate 2: bank_txn 2 written"


def test_the_readme_example_runs_as_written():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    code = re.search(r"<!-- example: app/validate -->\s*```python\n(.*?)```", text, re.S).group(1)
    exec(compile(code, "README.md example", "exec"), {})


_PATH = re.compile(r"(?<![\w/.-])((?:app|tests|evals|scripts|fixtures|docs)/[\w./-]*[\w-](?:::\w+)?"
                   r"|config\.yaml|pyproject\.toml|Makefile)")
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")  # a markdown link's target


def tail(symbol: str) -> str:
    """A symbol cited by its start ('test_ac4_...') matches any name it begins."""
    return r"\w*" if symbol.endswith("_") else r"\b"


def _missing(page: Path) -> list[str]:
    text = page.read_text(encoding="utf-8")
    missing = []
    cited = [m.group(1) for m in _PATH.finditer(text)]
    cited += [m.group(1) for m in _LINK.finditer(text) if "://" not in m.group(1)]
    for ref in cited:
        path, _, symbol = ref.partition("::")
        if "<" in path or "*" in path:
            continue
        found = next((p for p in (ROOT / path, page.parent / path) if p.exists()), None)  # repo path or link
        if found is None:
            missing.append(path)
        elif symbol and not re.search(rf"\b(?:def|class)\s+{re.escape(symbol)}{tail(symbol)}|^{re.escape(symbol)}\s*=",
                                      found.read_text(encoding="utf-8"), re.M):
            missing.append(ref)
    return missing


@pytest.mark.parametrize("page", PAGES + EVAL_READMES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_path_link_and_symbol_a_page_cites_exists(page):
    assert _missing(page) == []


def test_the_citation_check_sees_a_dead_path_a_dead_link_and_a_dead_symbol(tmp_path):
    page = tmp_path / "page.md"
    page.write_text("See `app/no_such.py`, [here](nowhere.md), and `app/web/actions.py::no_such_function`.\n"
                    "But `app/web/actions.py::explain_debit`, `tests/test_phase7_exit.py::test_ac4_...` and "
                    "[the permission model](docs/permission-model.md) are fine.",
                    encoding="utf-8")
    assert sorted(_missing(page)) == ["app/no_such.py", "app/web/actions.py::no_such_function", "nowhere.md"]


# The figures a run prints: rates, counts of runs, checks, steps and tests, model calls and money.
_FIGURE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:%|percent\b)"
    r"|\b\d[\d,]*\s+(?:of|/)\s*\d[\d,]*\s+(?:runs?|scenarios?|checks?|steps?|tests?|times)\b"
    r"|\b\d+\s*/\s*\d+\s+(?:runs?|scenarios?|checks?|steps?|pass(?:ed)?)\b"
    r"|\b\d[\d,]*\s+(?:tests?\s+|runs?\s+|checks?\s+)?(?:passed|failed)\b"
    r"|\b\d[\d,]*\s+model calls\b"
    r"|\b\d[\d,]*\s*(?:µUSD|micro-USD)|US\$\s?\d|\$\d+\.\d\d"
    r"|\b(?:success )?rate\s+(?:of\s+)?\d(?:\.\d+)?\b", re.I)
# Not results but settings, quoted by name in the docs: the budget guard's caps and the step-cap variant.
_SETTINGS = ("600 model calls", "5,000,000 micro-USD", "600 calls or 5,000,000 micro-USD", "(US$5)")


def figures(text: str) -> list[str]:
    for setting in _SETTINGS:
        text = text.replace(setting, "")
    return _FIGURE.findall(text)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_hand_written_page_types_a_result_figure(page):
    assert figures(page.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("line", [
    "19 of 19 steps passed; 52 of 52 checks.", "38 model calls, 0 µUSD", "1,412 passed in 91s", "5/5 runs pass",
    "a success rate 1.00", "cost US$0.42", "100 percent of scenarios", "all 11 scenarios passed 5 of 5 times",
    "55 of 55 runs passed (100%)", "it cost $1.37"])
def test_the_figure_detector_sees_what_the_reports_print(line):
    assert figures(line) != []


def test_the_readme_names_every_app_module_app_validate_imports():
    import ast

    needed = set()
    for f in (ROOT / "app" / "validate").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.domain"):
                needed.add(node.module.removeprefix("app.domain").lstrip(".") or "__init__")
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    sentence = text[text.index("project can lift the package with"):][:200]
    assert needed and all(f"{m}.py" in sentence for m in needed), (needed, sentence)


def test_the_eval_readme_tells_the_live_runs_in_order():
    """PO (batch 8 verdict; CHG-036; CHG-055): the pilot's failure, the trace, the root cause, the fix, the AFTER."""
    text = (EVALS / "3-improvement-and-regression" / "README.md").read_text(encoding="utf-8")
    story = text[text.index("## The live runs, in order"):text.index("## The regression, told straight (D23)")]
    marks = ["(live-pilot-before/report.md)", "(live-pilot-before/traces/README.md)", "root causes", "The fixes",
             "(live-pilot-after/README.md)", "../raw-runs/2026-10-04-live-baseline/"]
    at = [story.index(m) for m in marks]
    assert at == sorted(at), dict(zip(marks, at))


# --- every relative link resolves, its anchor included (CHG-055) ---------------------------------------------

_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^```.*?^```", re.M | re.S)


def anchors(page: Path) -> set[str]:
    """The anchors GitHub gives a page's headings: lower case, punctuation dropped, spaces as hyphens."""
    text = _FENCE.sub("", page.read_text(encoding="utf-8"))
    return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
            for h in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", text, re.M)}


def dead_links(page: Path) -> list[str]:
    dead = []
    for target in _MD_LINK.findall(_FENCE.sub("", page.read_text(encoding="utf-8"))):
        if "://" in target or target.startswith("mailto:"):
            continue
        path, _, anchor = target.partition("#")
        found = page if not path else (page.parent / path)
        if not found.exists():
            dead.append(target)
        elif anchor and found.suffix == ".md" and anchor not in anchors(found):
            dead.append(target)
    return dead


MARKDOWN = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]


@pytest.mark.parametrize("page", MARKDOWN, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_relative_link_resolves_to_a_file_and_its_anchor(page):
    assert dead_links(page) == []


def test_the_link_check_sees_a_dead_file_and_a_dead_anchor(tmp_path):
    (tmp_path / "other.md").write_text("# The regression, told straight (D23)\n## Full-workflow runs\n",
                                       encoding="utf-8")
    page = tmp_path / "page.md"
    page.write_text("[a](other.md#the-regression-told-straight-d23) [b](other.md#full-workflow-runs) "
                    "[c](gone.md) [d](other.md#no-such-heading) [e](https://example.com/x) [f](#here)\n# Here\n"
                    "```\n[g](inside-a-fence.md)\n```\n", encoding="utf-8")
    assert dead_links(page) == ["gone.md", "other.md#no-such-heading"]


# --- the figures the eval READMEs quote are their reports' own (CHG-055; D25) -------------------------------

_EVAL_FIGURE = re.compile(r"\b\d+\s*/\s*\d+\b|\b\d+\s+points?\b|\b\d+\s+(?:scenarios?|runs?|failed checks?)\b",
                          re.I)


def _report(folder: str) -> dict:
    import json

    return json.loads((EVALS / folder / "report.json").read_text(encoding="utf-8"))


def quoted() -> dict[str, str]:
    """Every figure the eval READMEs quote, as words around it, derived here from the report it comes from.
    A README may quote a figure only inside one of these."""
    import json

    def finished(row_or_totals: dict) -> int:
        return row_or_totals["runs"] - row_or_totals["errored"]

    def pts(x: float) -> str:
        return f"{x * 100:.0f}"

    q = {}
    live = _report("1-eval-report/live-11x5")
    t, cov = live["totals"], live["coverage"]
    (per,) = cov["runs_per_scenario"]
    q["live"] = f"{t['passed']} of {finished(t)} live runs passed ({t['scenarios']} scenarios × {per} runs)"
    first = {}
    for row in live["scenarios"]:
        tried = cov["replaced"].get(row["scenario"]) or [
            {"passed": row["passed"], "finished": finished(row), "errored": row["errored"]}]
        first[row["scenario"]] = next(x for x in tried if x["finished"])
    clean = sum(x["passed"] == x["finished"] == per for x in first.values())
    q["first"] = (f"{clean} of {len(first)} scenarios passed {per}/{per} in the first invocation that finished "
                  "their runs")
    h04 = cov["replaced"]["04-hinglish-voice-note"]
    said = [f"{x['passed']}/{x['finished']}" for x in h04]
    q["s04"] = f"scenario 04 failed ({said[0]}, then {said[1]}), was fixed, and passed {said[2]} on rerun"
    commits = {s["report"]: s["commit"] for s in live["meta"]["sources"]}
    q["s04-commits"] = ", ".join(f"{s} at {commits[x['source']]}" for s, x in zip(said, h04))

    off = _report("1-eval-report/offline-14x5")
    q["offline"] = (f"{off['totals']['passed']} of {finished(off['totals'])} offline runs passed "
                    f"({off['totals']['scenarios']} scenarios × {off['meta']['runs_per_scenario']} runs)")

    abl = _report("2-harness-ablation/live")
    q["ablation"] = (f"{pts(abl['full_vs_bare'])} points of outcome success, paired on the "
                     f"{abl['paired_on']['bare']} scenarios both scored")
    q["full-bare"] = (f"full {pts(abl['harnesses']['full']['success'])}%, bare "
                      f"{pts(abl['harnesses']['bare']['success'])}%")
    top = abl["earned_most"]
    (lost,) = {len(abl["lost"][h]) for h in top}
    assert {n for h in top for n in abl["harnesses"][h]["runs_per_cell"].values()} == {1}  # what "once" says
    q["earned"] = (f"{' and '.join(top)} cost the most: {pts(abl['drops'][top[0]])} points each, which at one run "
                   f"per scenario is {lost} scenario each")
    (scored,) = set(abl["not_measured"].values())
    q["unmeasured"] = (f"{' and '.join(sorted(abl['not_measured']))}: not measured live ({scored}/"
                       f"{len(abl['scenarios'])} scenarios)")

    pilot, after = _report("3-improvement-and-regression/live-pilot-before"), \
        _report("3-improvement-and-regression/live-pilot-after")
    q["pilot"] = (f"passed {pilot['totals']['scenarios_all_runs_passed']} of {pilot['totals']['scenarios']} "
                  "scenarios")
    q["after"] = f"{after['totals']['passed']} of {finished(after['totals'])} runs passed"

    reg = _report("3-improvement-and-regression/regression-caught")
    (r07,) = [r for r in reg["scenarios"] if r["scenario"] == "07-missed-alert-causes-drift"]
    q["regression"] = (f"its path check failed in {r07['path'][1] - r07['path'][0]} of {r07['path'][1]} runs of "
                       f"scenario 07, while {reg['totals']['passed']} of {finished(reg['totals'])} finished runs "
                       "still passed")

    failed = []
    for run in ("A", "B"):
        data = json.loads((EVALS / "4-end-to-end-workflows" / f"workflow-{run}-2026-10-04-live.json").read_text(
            encoding="utf-8"))
        failed.append([c["id"] for r in data["repeats"] for s in r["steps"] for c in s["checks"] if not c["ok"]])
    (n,) = {len(f) for f in failed}
    q["workflows"] = (f"live, A and B each left {n} failed check (`{failed[0][0]}` in A, `{failed[1][0]}` in B)"
                      if n == 1 else f"live, A and B each left {n} failed checks")
    return q


@pytest.mark.parametrize("page", EVAL_READMES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_figure_an_eval_readme_quotes_is_read_from_its_report(page):
    text = page.read_text(encoding="utf-8")
    spans = [(m.start(), m.end()) for q in quoted().values() for m in re.finditer(re.escape(q), text)]
    loose = [m.group(0) for m in [*_FIGURE.finditer(text), *_EVAL_FIGURE.finditer(text)]
             if not any(a <= m.start() and m.end() <= b for a, b in spans)]
    assert loose == []


def test_every_derived_quote_is_on_an_eval_readme():
    text = "\n".join(p.read_text(encoding="utf-8") for p in EVAL_READMES)
    assert [k for k, q in quoted().items() if q not in text] == []


def test_the_live_suite_headline_never_appears_without_scenario_04s_story():
    """PO, CHG-055 AC5: wherever a page shows the live suite's total, the sentence on scenario 04 (failed, fixed,
    passed on rerun) is on the same line; on the combined page, its Coverage line comes right before."""
    q = quoted()
    shown = 0
    for page in sorted(set(EVAL_READMES) | set(MARKDOWN)):
        for line in page.read_text(encoding="utf-8").splitlines():
            if q["live"] in line:
                shown += 1
                assert q["s04"] in line, (page.name, line)
    assert shown >= 2
    md = (EVALS / "1-eval-report" / "live-11x5" / "report.md").read_text(encoding="utf-8").splitlines()
    (at,) = [i for i, line in enumerate(md) if line.startswith("**Totals:**")]
    h04 = _report("1-eval-report/live-11x5")["coverage"]["replaced"]["04-hinglish-voice-note"]
    assert md[at - 2].startswith("**Coverage:**") and all(
        f"{x['passed']}/{x['finished']} in `{x['source'].split('/')[-1]}`" in md[at - 2] for x in h04)


def test_the_eval_figure_check_sees_a_typed_figure():
    text = "55 of 55 live runs passed, 80 points, 4/5 then 0/5, 10 scenarios"
    assert len(_EVAL_FIGURE.findall(text) + _FIGURE.findall(text)) >= 5
