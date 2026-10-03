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


_PATH = re.compile(r"(?<![\w/.-])((?:app|tests|evals|scripts|fixtures|docs)/[\w./-]*[\w-])")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_path_a_page_cites_exists(page):
    missing = []
    for m in _PATH.finditer(page.read_text(encoding="utf-8")):
        path = m.group(1).split("::")[0]
        if "<" in path or "*" in path:
            continue
        if not (ROOT / path).exists() and not (page.parent / path).exists():  # a repo path, or a link from the page
            missing.append(path)
    assert missing == []


_FIGURE = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+\s+(?:tests|runs) (?:passed|failed)|\b\d+ of \d+ (?:runs|scenarios)")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_hand_written_page_types_a_result_figure(page):
    assert _FIGURE.findall(page.read_text(encoding="utf-8")) == []
