"""The case file (TDD Part 2, "The case file"): five parts, rendered by code
from the case's state. Goal, facts and unknowns come from code when the case
opens; findings (each with its source) and notes are added step by step. A
tool result is cut to 20 lines here; the full result goes in the trace."""

from __future__ import annotations

from typing import Any

MAX_RESULT_LINES = 20
SECTIONS = ("Goal", "Facts", "Findings", "Unknowns", "Notes")


def parse_opening(md: str) -> dict[str, Any]:
    """Goal, facts and unknowns from the file the reconciler opened the case
    with (app/ledger/reconcile.py, case_file)."""
    parts: dict[str, list[str]] = {name: [] for name in SECTIONS}
    current = None
    for line in md.splitlines():
        if line.startswith("## ") and line[3:].strip() in parts:
            current = line[3:].strip()
        elif current and line.strip() and line.strip() != "(none yet)":
            parts[current].append(line[2:] if line.startswith("- ") else line)
    return {"goal": " ".join(parts["Goal"]), "facts": parts["Facts"], "unknowns": parts["Unknowns"],
            "findings": [], "notes": []}


def cut(text: str) -> tuple[list[str], int]:
    """The first 20 lines of a tool result, and how many were left out."""
    lines = text.splitlines() or ["(nothing)"]
    return lines[:MAX_RESULT_LINES], max(len(lines) - MAX_RESULT_LINES, 0)


def finding(step: int, tool: str, args_text: str, result: str) -> dict[str, Any]:
    lines, more = cut(result)
    return {"step": step, "source": f"{tool}({args_text})", "lines": lines, "more": more}


def render(state: dict[str, Any]) -> str:
    out = ["## Goal", state.get("goal") or "(none)", "", "## Facts"]
    out += [f"- {f}" for f in state.get("facts", [])] or ["(none)"]
    out += ["", "## Findings"]
    findings = state.get("findings", [])
    if not findings:
        out.append("(none yet)")
    for f in findings:
        out.append(f"- step {f['step']}, source {f['source']}:")
        out += [f"    {line}" for line in f["lines"]]
        if f.get("more"):
            out.append(f"    (+{f['more']} more lines in the trace)")
    out += ["", "## Unknowns"]
    out += [f"- {u}" for u in state.get("unknowns", [])] or ["(none)"]
    out += ["", "## Notes"]
    out += [f"- {n}" for n in state.get("notes", [])] or ["(none yet)"]
    return "\n".join(out) + "\n"
