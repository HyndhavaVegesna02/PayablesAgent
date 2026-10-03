"""The exception agent's permission table (batch 6, CHG-008, S8), made from
the tools' own annotations, so docs/notes/agent-permissions.md cannot say
something the code does not (tests/test_phase7_exit.py compares them).

    python -m app.agent.permissions    # prints the table for the note"""

from __future__ import annotations

from app.agent.tools import TOOLS

ANNOTATIONS = {
    "read_only": "reads; writes nothing",
    "reads_mail": "reads this business's mailbox",
    "writes_candidate": "writes a candidate row (and the message it came from); never the ledger",
    "asks_owner": "writes one owner question",
    "ends_run": "ends the run until the owner answers",
}
BEGIN = "<!-- generated: python -m app.agent.permissions -->"
END = "<!-- end generated -->"


def table() -> str:
    lines = [BEGIN, "| Tool | Arguments | May | Summary |", "| --- | --- | --- | --- |"]
    for spec in TOOLS.values():
        args = ", ".join(spec.args_model.model_fields)
        may = "; ".join(ANNOTATIONS[a] for a in sorted(spec.annotations))
        lines.append(f"| `{spec.name}` | {args} | {may} | {spec.summary} |")
    lines.append(END)
    return "\n".join(lines)


if __name__ == "__main__":
    print(table())
