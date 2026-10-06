"""Checks that every committed fixture-mode report still says what the code
emits (CHG-032; batch 8 review, round 2). Each report in docs/evals/'s
numbered folders and raw-runs/ (evals/layout.py; CHG-055; not superseded/
or invalid/) whose meta says mode "fixtures" is regenerated in a
temporary folder with the arguments its meta records, and each of its .md
and .json files is compared with the committed one. Only the commit and date
fields may differ. Live reports are not reproducible and are left alone, but
a combined report (CHG-035), live or not, is re-derived from the reports it
names and must match exactly.

    uv run python scripts/check_evidence.py      # make check-evidence; exit 1 on any difference

It reruns the eval suites and the ablation in fixture mode (about a minute),
so it is not part of make test; it is a required step at batch close
(.yourteam/definition-of-done.md)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "docs" / "evals"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def report_files() -> list[Path]:
    """Every report.json and workflow report in the numbered folders and raw-runs, at any depth, outside the
    traces a report keeps."""
    from evals import layout

    found = []
    for root in layout.report_roots(EVALS):
        found += sorted(p for pattern in ("report.json", "workflow-*.json") for p in root.rglob(pattern)
                        if "traces" not in p.relative_to(root).parts)
    return found


def committed() -> list[tuple[str, Path, dict]]:
    """(kind, report.json path, meta) for each fixture-mode report, suite and ablation folders and workflow runs."""
    found = []
    for path in report_files():
        meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
        if meta.get("kind") in ("combined", "ablation-combined"):  # derived from other reports: re-derived offline
            found.append((meta["kind"], path, meta))
            continue
        if meta.get("mode") != "fixtures":
            continue
        kind = "workflow" if path.name.startswith("workflow-") else (
            "ablation" if "harnesses" in json.loads(path.read_text(encoding="utf-8")) else "suite")
        found.append((kind, path, meta))
    return found


def regenerate(kind: str, meta: dict, out: Path, at: str | None = None) -> Path:
    """Runs what made the report, into `out`; returns the fresh report.json. `at` is a combined page's folder
    under docs/evals, which its links are relative to."""
    from evals import ablation, report, runner, workflow

    if kind in ("combined", "ablation-combined"):  # from its sources where they are now, for the page where it is
        parts = report.load_parts([EVALS / s["report"] for s in meta["sources"]], EVALS)
        combine, write = ((report.combine, report.write_combined) if kind == "combined" else
                          (report.ablation_combine, report.write_ablation_combined))
        fresh = write(combine(parts, meta["label"], at), out / kind) / "report.json"
    elif kind == "suite":
        args = ["--ai", "fixtures", "--runs", str(meta["runs_per_scenario"]), "--label", meta["label"],
                "--out", str(out)]
        if meta.get("variant"):
            args += ["--config", meta["variant"]]  # as the report recorded it, relative to the repo root
        runner.main(args)
        (fresh,) = out.glob(f"*-fixtures-{meta['label']}/report.json")
    elif kind == "ablation":
        ablation.main(["--ai", "fixtures", "--runs", str(meta["runs_per_scenario"]), "--label", meta["label"],
                       "--out", str(out)])
        (fresh,) = out.glob(f"*-fixtures-{meta['label']}/report.json")
    else:
        workflow.main(["--ai", "fixtures", "--run", meta["run"], "--out", str(out)])
        (fresh,) = out.glob(f"workflow-{meta['run']}-*.json")
    return fresh


def _blank(text: str, meta: dict) -> str:
    if meta.get("kind") in ("combined", "ablation-combined"):  # its commits and dates are its sources'; exact
        return text
    return text.replace(str(meta["commit"]), "<commit>").replace(str(meta["date"]), "<date>")


def differences(old_json: Path, new_json: Path) -> list[str]:
    """The files of a report that differ beyond their commit and date."""
    old_meta = json.loads(old_json.read_text(encoding="utf-8"))["meta"]
    new_meta = json.loads(new_json.read_text(encoding="utf-8"))["meta"]
    out = []
    for old, new in ((old_json, new_json), (old_json.with_suffix(".md"), new_json.with_suffix(".md"))):
        a = _blank(old.read_text(encoding="utf-8"), old_meta).splitlines()
        b = _blank(new.read_text(encoding="utf-8"), new_meta).splitlines()
        if a != b:
            first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            out.append(f"{old.relative_to(ROOT).as_posix()}: line {first + 1} differs"
                       + (f" ({len(a)} vs {len(b)} lines)" if len(a) != len(b) else ""))
    return out


def main() -> int:
    import os

    before = os.getcwd()
    os.chdir(ROOT)  # the reports record repo-relative paths (a variant's config)
    try:
        return _check()
    finally:
        os.chdir(before)


def _check() -> int:
    reports = committed()
    if not reports:
        print("no fixture-mode reports under docs/evals/")
        return 1
    problems = []
    with tempfile.TemporaryDirectory(prefix="check-evidence-") as tmp:
        for i, (kind, path, meta) in enumerate(reports):
            out = Path(tmp) / str(i)
            gone = [s["report"] for s in meta.get("sources", []) if not (EVALS / s["report"] / "report.json").exists()]
            if gone:
                problems.append(f"{path.relative_to(ROOT).as_posix()}: its sources {gone} are not under docs/evals/ "
                                "(moved?); combine it again from where they are")
                continue
            at = path.parent.relative_to(EVALS).as_posix()
            problems += differences(path, regenerate(kind, meta, out, at))
            print(f"checked {path.relative_to(ROOT).as_posix()}", flush=True)
    if problems:
        print("\n".join(["The committed evidence no longer matches what the code emits:", *problems,
                         "Regenerate it at a clean commit and keep the old copy under docs/evals/superseded/."]))
        return 1
    print(f"all {len(reports)} reports reproduce: fixture-mode ones below their commit and date, combined ones "
          "exactly (md and json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
