"""The evidence documents (batch 7, CHG-010c) say only what the code does:
their generated tables and traces are regenerated and compared, the README's
example runs as written, every path they cite exists, and no hand-written
page types a result figure (D25: figures live in generated reports, which
name their commit)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "docs" / "evals" / "README.md",
         ROOT / "docs" / "traces" / "README.md"]


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


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(ROOT).as_posix())
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
    """PO (batch 8 verdict; CHG-036): the pilot's failure, the trace, the root cause, the fix, the AFTER."""
    text = (ROOT / "docs" / "evals" / "README.md").read_text(encoding="utf-8")
    story = text[text.index("## The live runs, in order"):text.index("## Full-workflow runs")]
    marks = ["2026-10-04-live-pilot/`", "2026-10-04-live-pilot/traces/", "root causes", "docs/batches/2026-10-04-8/",
             "2026-10-04-live-after-batch-8/", "2026-10-04-live-baseline/"]
    at = [story.index(m) for m in marks]
    assert at == sorted(at), dict(zip(marks, at))
