"""Where the eval reports live (CHG-055). docs/evals is laid out by what each
part of it shows: a numbered folder per deliverable, holding the pages a
reader starts from, and raw-runs/, holding every invocation those pages were
built from, under its original dated name. New runs land in raw-runs/ (a
suite or an ablation) or with the other workflow reports, never at the top."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "docs" / "evals"
RAW_RUNS = EVALS / "raw-runs"  # make evals, make ablation
WORKFLOWS = EVALS / "4-end-to-end-workflows"  # make workflow
OFFLINE_ABLATION = "2-harness-ablation/offline"  # under EVALS: the fixture ablation, every scenario scored
_SHOWN = re.compile(r"^\d+-")  # a numbered folder: what a reader starts from


def report_roots(evals: Path = EVALS) -> list[Path]:
    """The folders that hold the reports: each numbered folder, then raw-runs."""
    return sorted(p for p in evals.iterdir() if p.is_dir() and _SHOWN.match(p.name)) + [
        p for p in [evals / RAW_RUNS.name] if p.is_dir()]


def under(path: Path, evals: Path = EVALS) -> str:
    """A report folder's name as a combined report records it: its path under docs/evals, or its own name
    when it lies elsewhere."""
    try:
        return path.resolve().relative_to(evals.resolve()).as_posix()
    except ValueError:
        return path.name
