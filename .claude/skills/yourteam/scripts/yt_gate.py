#!/usr/bin/env python3
"""YourTeam gate runner.

Runs every command in the project's Definition of Done and emits the
`dod_evidence` YAML fragment — command, exit code, output tail, commit SHA,
timestamp. With `--record CHG-NNN` it appends that fragment straight into the
change's `gate_evidence` in batch.yaml, so evidence is captured mechanically
rather than transcribed by hand. Without `--record` it only prints, and printing
something nothing files is how hand-transcription becomes mandatory — so pass it.

Rules this script enforces by construction:
  * Commands run SEQUENTIALLY, never concurrently (working agreement
    2026-07-02: two runners sharing one throwaway DB corrupt each other).
  * The gate refuses a dirty tree ( a gate
    result only counts at a clean, committed HEAD). --allow-dirty overrides
    for diagnostic runs; such runs are NOT valid DoD evidence.
    EXCEPTION: modified ORCHESTRATOR-OWNED paths
    (`.yourteam/`) are reported but never gate. They are read by no gate
    command, so they cannot change a result — while the orchestrator edits
    them continuously, including while an agent runs. Refusing on them
    bought nothing and left agents with no sanctioned move.
  * A contention false-red is proven, not assumed: re-run the failing unit with --only in isolation; if it
    passes AND its diff since the batch cut is empty, record the isolated
    re-run with a prominent note and file a determinism defect.
  * A command that looks environment-blocked (a Windows Device Guard /
    Application Control policy, not the code) is LABELLED as such —
    `is_policy_block()`, platform-level signatures only — but the label
    never downgrades a red: exit_code is recorded faithfully and still
    fails the gate.

DoD file format (parsed from .yourteam/definition-of-done.md):
  * Sections whose heading starts with `## Commands` hold gate commands.
  * A heading may set the working directory for its section with the
    phrase "run from <dir>/" (e.g. "## Commands (frontend — ..., run
    from `frontend/`)").
  * Command lines look like:  - [ ] <label>: `<command>` -> exit 0

Usage:
  python yt_gate.py                 # run the full gate, print YAML evidence
  python yt_gate.py --list          # parse and show what would run
  python yt_gate.py --only pytest   # run only commands containing "pytest"
  python yt_gate.py --out ev.yaml   # also write the fragment to a file

Exit codes: 0 all commands passed; 1 at least one failed; 3 dirty tree
(without --allow-dirty); 4 could not parse any commands.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

CMD_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s*(.+?):\s*`([^`]+)`")
HEADING_RE = re.compile(r"^##\s+(.*)$")
# Optional per-command env-precondition annotation on a DoD line:
# `(requires-env: DATABASE_URL, DATABASE_URL_DIRECT)`. Project-supplied — the
# runner hardcodes no var names, staying generic.
REQUIRES_ENV_RE = re.compile(r"\(requires-env:\s*([^)]*)\)", re.IGNORECASE)
CWD_RE = re.compile(r"run from\s+`?([\w./\\-]+?)/?`?[\s),]", re.IGNORECASE)
TAIL_CHARS = 600


def find_root(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / ".yourteam").is_dir():
            return p
    return None


def parse_dod(dod_path: Path) -> list[dict]:
    """Return [{label, command, cwd}] from the DoD file's Commands sections."""
    commands: list[dict] = []
    in_commands, section_cwd = False, ""
    for line in dod_path.read_text(encoding="utf-8", errors="replace").splitlines():
        h = HEADING_RE.match(line)
        if h:
            heading = h.group(1)
            in_commands = heading.strip().lower().startswith("commands")
            m = CWD_RE.search(heading)
            section_cwd = m.group(1) if (in_commands and m) else ""
            continue
        if not in_commands:
            continue
        m = CMD_RE.match(line)
        if m:
            # Optional, project-supplied: `(requires-env: VAR1, VAR2)` anywhere on
            # the DoD line declares env preconditions the gate warns about up front
            # when unset. The project names its own vars, so the runner stays
            # generic.
            rm = REQUIRES_ENV_RE.search(line)
            requires_env = (
                [v.strip() for v in rm.group(1).split(",") if v.strip()] if rm else []
            )
            commands.append(
                {
                    "label": m.group(1).strip(),
                    "command": m.group(2).strip(),
                    "cwd": section_cwd,
                    "requires_env": requires_env,
                }
            )
    return commands


def git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, timeout=30
    )
    return out.stdout.strip()


#: Paths the orchestrator owns and edits continuously, including while an agent
#: is running. They are exempted from the dirty-tree refusal below, because
#: refusing on them boxes an agent in: it needs clean-tree evidence, cannot
#: write these files itself, and its only escape is `git stash` — which has
#: twice cost more than the refusal ever protected (one stash swallowed the
#: orchestrator's own board; another popped an unrelated stash and left conflict
#: markers across the source tree). Removing the incentive is the fix; the
#: "agents never write .yourteam/" rule is unaffected.
#:
#: The safety of this exemption rests on one condition: any gate command that
#: reads these paths must read the COMMITTED tree at HEAD, never the working
#: tree. Otherwise a result stamped `commit: X` could reflect a working state
#: that X never contained — dirty-tree-green evidence, which is exactly the
#: failure mode this gate exists to make impossible. Add a .yourteam/-reading
#: check without that discipline and you reopen the hole.
_ORCHESTRATOR_OWNED_PREFIXES = (".yourteam/",)


def _status_path(line: str) -> str:
    """The path from a `git status --porcelain` line, normalised to forward slashes.

    Porcelain v1 is `XY <path>`, with a rename as `XY <old> -> <new>`; the
    destination is what matters. Quoted paths (non-ASCII, spaces) keep their
    quotes — harmless here, since we only prefix-match a known ASCII directory.

    *** DO NOT slice at a fixed offset. *** `git()` calls `.strip()` on the whole
    output, so the FIRST line of a run loses its leading space: ` M .yourteam/x`
    arrives as `M .yourteam/x`. A `line[3:]` slice then eats the leading `.` and
    `.yourteam/x` silently stops matching — which is precisely the bug this function
    shipped with, caught only by running the gate for real against a tree dirtied
    by exactly one `.yourteam/` file. Split on whitespace instead; the status code is
    always a 1-2 char non-space token.
    """
    parts = line.strip().split(None, 1)
    path = parts[1] if len(parts) > 1 else ""
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip().strip('"').replace("\\", "/")


def is_orchestrator_owned(line: str) -> bool:
    """True if this status line names a path the orchestrator owns (A20)."""
    return _status_path(line).startswith(_ORCHESTRATOR_OWNED_PREFIXES)


def tree_state(root: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (dirty_lines, untracked_lines, orchestrator_owned_lines).

    A20: modified ORCHESTRATOR-OWNED paths are split out of `dirty` and reported
    separately rather than refused. Their WORKING-TREE state cannot change a
    result -- not because nothing reads them, but
    because the suites that read them read the COMMITTED tree at HEAD. See the
    corrected note on `_ORCHESTRATOR_OWNED_PREFIXES`. Every other modified
    tracked file still refuses.
    """
    lines = [ln for ln in git(root, "status", "--porcelain").splitlines() if ln.strip()]
    untracked = [ln for ln in lines if ln.startswith("??")]
    tracked = [ln for ln in lines if not ln.startswith("??")]
    owned = [ln for ln in tracked if is_orchestrator_owned(ln)]
    dirty = [ln for ln in tracked if not is_orchestrator_owned(ln)]
    return dirty, untracked, owned


def _is_banner(line: str) -> bool:
    """Decorative ASCII-art line (e.g. import-linter's box-drawing logo)?

    Such lines carry zero evidence signal but cost bytes in batch.yaml
    forever. A line is a banner when box-drawing/
    block/geometric glyphs (U+2500-U+25FF) dominate it; lines with a stray
    glyph (vite's `140 kB │ gzip: 76 kB`) are kept.
    """
    solid = [ch for ch in line if not ch.isspace()]
    if not solid:
        return False
    deco = sum(1 for ch in solid if "─" <= ch <= "◿")
    return deco / len(solid) > 0.5


#: ANSI/VT escape sequences (colour, cursor moves) emitted by tools that detect
#: — or merely assume — a terminal. `\x1b[32m`, `\x1b[0m`, and friends.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")


def _strip_control_chars(text: str) -> str:
    """Remove ANSI escapes and C0 control characters from captured output.

    The emitted `dod_evidence` fragment is meant to be merged into the batch
    board VERBATIM, and YAML **forbids** raw C0 control characters outright:
    a single stray `\\x1b` makes the whole board unparseable
    (`yaml.reader.ReaderError: special characters are not allowed`), which is a
    far worse failure than a slightly less pretty tail.

    Amendment A10. Motivating
    incident: a project's frontend build colourised its output, the tail was
    pasted verbatim exactly as instructed, and the batch board became
    unreadable. Sanitising here fixes it for every project rather than warning
    each one — any build tool that colourises hits this.

    Tabs and newlines are preserved; `one_line_tail` collapses newlines itself.
    """
    return "".join(ch for ch in _ANSI_ESCAPE.sub("", text) if ch >= " " or ch in "\n\t")


def one_line_tail(text: str, limit: int = TAIL_CHARS) -> str:
    # Sanitise BEFORE slicing: escape sequences are multi-byte, so trimming
    # first can leave a half-sequence whose ESC survives the filter's intent.
    tail = _strip_control_chars(text).strip()[-limit:]
    tail = " | ".join(
        part.strip()
        for part in tail.splitlines()
        if part.strip() and not _is_banner(part)
    )
    return tail.replace("\\", "\\\\").replace('"', '\\"')


#: Observed signatures of a Windows Device Guard /
#: Application Control policy blocking a process, rather than the invoked
#: command genuinely failing. Platform-level, not project-level — no project
#: names, paths or command names belong here, which is why this lives in the
#: generic runner instead of a per-project DoD note.
POLICY_BLOCK_EXIT_CODE = 4551
_POLICY_BLOCK_MARKERS = (
    re.compile(r"blocked by your organization", re.IGNORECASE),
    re.compile(r"application control policy has blocked", re.IGNORECASE),
)

#: The 2026-07-06 working agreement's proof protocol, restated here so AC3's
#: label always ships with it: a policy-block classification is not license
#: to discount a red on sight.
POLICY_BLOCK_PROOF_NOTE = (
    "This is a LABEL, not an escape hatch (agreement 2026-07-06): a policy-blocked "
    "command still exits nonzero, still records its exit code faithfully, and still "
    "fails the gate. Before discounting it, prove BOTH: (1) an EMPTY diff on the "
    "affected command/file since the batch cut, AND (2) the command passes when "
    "re-run in isolation with --only. A red without both proven stays a red."
)


def is_policy_block(exit_code: int, output: str) -> bool:
    """Classify a command result as an environment (policy) block, not a code failure.

    AC5 (two-sided): fires on the observed signatures — exit code 4551 and/or
    the marker text a Windows Application Control policy itself emits in its
    block message — and must NOT fire on a genuine failure's output (e.g. a
    pytest assertion failure). A zero exit is never a block: a command that
    merely prints marker-like text while succeeding is not blocked (AC4 —
    the label only ever attaches to something that is already a red).
    """
    if exit_code == 0:
        return False
    if exit_code == POLICY_BLOCK_EXIT_CODE:
        return True
    return any(pattern.search(output) for pattern in _POLICY_BLOCK_MARKERS)


_ENV_REF = re.compile(r"\$\{(\w+)\}|\$(\w+)|%(\w+)%")


def preflight_env(commands: list, env: dict) -> list:
    """Generic, project-agnostic precondition scan.

    A command whose env precondition is unset produces a false-red that looks
    nothing like the code failing — e.g. a DB-backed migration/consistency
    command left without its connection URL surfaces a raw KeyError, costing a
    diagnose-and-re-run cycle. This warns UP FRONT
    and names the missing vars, without hardcoding any project's var names.

    Two signals, both project-supplied (the runner stays generic):
      - a `(requires-env: VAR, ...)` annotation on the DoD line — the reliable
        signal, since the dependency is usually INSIDE the invoked code
        (`os.environ[...]`), not literally in the command string; and
      - a literal `$VAR` / `${VAR}` / `%VAR%` reference in the command text
        (fallback, for shell-style commands).

    Returns the sorted list of required-but-unset var names (empty = clean).
    Advisory only: it never blocks — the command still runs and reds honestly
    if the missing var truly breaks it.
    """
    missing = set()
    for entry in commands:
        for name in entry.get("requires_env", []):
            if name not in env:
                missing.add(name)
        for m in _ENV_REF.finditer(entry["command"]):
            name = next(g for g in m.groups() if g)
            if name not in env:
                missing.add(name)
    return sorted(missing)


def run_command(entry: dict, root: Path, env: dict, timeout: int) -> dict:
    cwd = root / entry["cwd"] if entry["cwd"] else root
    started = datetime.datetime.now(datetime.timezone.utc)
    try:
        proc = subprocess.run(
            entry["command"],
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        exit_code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        output = f"TIMEOUT after {timeout}s: {exc}"
    return {
        "label": entry["label"],
        "command": entry["command"],
        "cwd": entry["cwd"],
        "exit_code": exit_code,
        "output_tail": one_line_tail(output),
        "at": started.isoformat(timespec="seconds"),
        # AC3/AC4: a LABEL only — exit_code above is recorded faithfully either
        # way and is the sole input to the gate's pass/fail decision.
        "policy_block": is_policy_block(exit_code, output),
    }


def emit_yaml(results: list[dict], commit: str) -> str:
    lines = ["dod_evidence:"]
    for r in results:
        cmd = r["command"].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  - command: "{cmd}"')
        lines.append(f"    exit_code: {r['exit_code']}")
        lines.append(f'    output_tail: "{r["output_tail"]}"')
        lines.append(f"    commit: {commit}")
        lines.append(f'    at: "{r["at"]}"')
    return "\n".join(lines) + "\n"


def record_evidence(batch_path: Path, change_id: str, results: list[dict], commit: str) -> str:
    """Append gate results into a change's `gate_evidence:` list in batch.yaml.

    This exists because the alternative is hand-transcription, which the skill
    forbids for good reason: a number copied by hand is a number that can be
    tidied. The script emitting clean YAML that nothing files is the same hole
    with an extra step.

    Append-only by construction. A red run followed by a green one at the fix
    commit must leave BOTH on the record -- overwriting the red one would erase
    the very history the gate exists to keep. Re-running the gate therefore adds
    entries; it never replaces them.

    Deliberately hand-rolled rather than round-tripped through a YAML library:
    a load-then-dump would reflow the file, strip its comments and reorder its
    keys, turning every gate run into a large unreviewable diff of state the
    human is supposed to be able to read.
    """
    if not batch_path.exists():
        return f"no {batch_path}, nothing recorded"

    text = batch_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # locate the change entry
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^(\s*)- id:\s*{re.escape(change_id)}\s*$", ln):
            start = i
            break
    if start is None:
        return f"{change_id} not found in {batch_path.name}; nothing recorded"

    item_indent = len(lines[start]) - len(lines[start].lstrip())
    field_indent = item_indent + 2

    # entry ends at the next sibling list item or a dedent out of the block
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind <= item_indent and (ln.lstrip().startswith("- ") or ind < item_indent):
            end = i
            break

    rows = []
    for r in results:
        cmd = r["command"].replace("\\", "\\\\").replace('"', '\\"')
        rows.append(
            f'{" " * (field_indent + 2)}- {{command: "{cmd}", exit_code: {r["exit_code"]}, '
            f'output_tail: "{r["output_tail"]}", commit: {commit}, at: {r["at"]}}}'
        )

    key = f'{" " * field_indent}gate_evidence:'
    existing = None
    for i in range(start + 1, end):
        if lines[i].rstrip() == key.rstrip() or re.match(rf"^{' ' * field_indent}gate_evidence:\s*(\[\])?\s*$", lines[i]):
            existing = i
            break

    if existing is None:
        lines[end:end] = [key] + rows
    else:
        if lines[existing].strip().endswith("[]"):
            lines[existing] = key
            insert = existing + 1
        else:
            insert = existing + 1
            while insert < end and lines[insert].strip().startswith("- "):
                insert += 1
        lines[insert:insert] = rows

    batch_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"recorded {len(rows)} result(s) under {change_id} in {batch_path.name}"


def main() -> int:
    # Windows consoles default to cp1252; captured tails are UTF-8 (may carry
    # npm's ✓ etc.), so force UTF-8 on our own streams or the evidence print
    # crashes after a fully green run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--record",
        metavar="CHG-NNN",
        default=None,
        help=(
            "append this run's results into that change's gate_evidence in "
            ".yourteam/batch.yaml instead of leaving them to be transcribed by hand. "
            "Ignored with --allow-dirty, which the script already treats as non-evidence."
        ),
    )
    ap.add_argument(
        "--dod",
        default=None,
        help="path to the DoD file (default .yourteam/definition-of-done.md)",
    )
    ap.add_argument(
        "--list", action="store_true", help="parse and list commands without running"
    )
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        help="run only commands containing this substring (repeatable)",
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="run despite a dirty tree (NOT valid DoD evidence)",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="per-command timeout in seconds (default 1800)",
    )
    ap.add_argument(
        "--out", default=None, help="also write the YAML fragment to this file"
    )
    args = ap.parse_args()

    root = find_root(Path.cwd().resolve())
    if root is None:
        print(
            "yt_gate: no .yourteam/ directory found walking up from cwd", file=sys.stderr
        )
        return 4

    dod_path = Path(args.dod) if args.dod else root / ".yourteam" / "definition-of-done.md"
    if not dod_path.exists():
        print(f"yt_gate: DoD file not found: {dod_path}", file=sys.stderr)
        return 4

    commands = parse_dod(dod_path)
    if args.only:
        commands = [
            c
            for c in commands
            if any(s.lower() in c["command"].lower() for s in args.only)
        ]
    if not commands:
        print(
            "yt_gate: no gate commands parsed (check the DoD file format)",
            file=sys.stderr,
        )
        return 4

    if args.list:
        for c in commands:
            loc = f" [cwd: {c['cwd']}]" if c["cwd"] else ""
            print(f"{c['label']}: {c['command']}{loc}")
        return 0

    dirty, untracked, owned = tree_state(root)
    if untracked:
        print(
            f"yt_gate: WARNING {len(untracked)} untracked file(s) present (not gating)",
            file=sys.stderr,
        )
    if owned:
        # A20: informational, never gating. Named individually so the run's
        # evidence records exactly what was modified and by whom it is owned.
        print(
            f"yt_gate: {len(owned)} orchestrator-owned path(s) modified, NOT gating "
            "(their committed state is what gate commands read -- see A20):",
            file=sys.stderr,
        )
        for ln in owned:
            print(f"yt_gate:   orchestrator-owned: {ln}", file=sys.stderr)
    if dirty:
        for ln in dirty:
            print(f"yt_gate: dirty: {ln}", file=sys.stderr)
        if not args.allow_dirty:
            print(
                "yt_gate: REFUSING dirty tree — the gate counts only at a clean committed HEAD "
                "(agreement 2026-06-29). Commit or discard, then re-run. --allow-dirty for "
                "diagnostics only.",
                file=sys.stderr,
            )
            return 3
        print(
            "yt_gate: --allow-dirty set — this run is NOT valid DoD evidence",
            file=sys.stderr,
        )

    # Make venv-sibling binaries (pytest, ruff, alembic, lint-imports) resolvable.
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    # Force UTF-8 in every gate subprocess: without it,
    # import-linter's rich banner crashes the Windows cp1252 pipe writer
    # (UnicodeEncodeError in rich/_win32_console.py) and reds an otherwise-green gate.
    # setdefault so a deliberately-exported PYTHONUTF8 still wins.
    env.setdefault("PYTHONUTF8", "1")

    # Precondition scan: a command referencing an
    # unset env var reds in a way that looks nothing like the code failing (a raw
    # KeyError / connection error), costing a diagnose-and-re-run cycle. Warn up
    # front and name the missing vars — generically, no project var names hardcoded.
    unset = preflight_env(commands, env)
    if unset:
        print(
            "yt_gate: WARNING these commands reference unset env var(s): "
            + ", ".join(unset)
            + " — a missing precondition (e.g. an unprovisioned DB/service) reds as a "
            "false failure. Set them (or provision the backing resource) before trusting "
            "the result. Running anyway.",
            file=sys.stderr,
            flush=True,
        )

    commit = git(root, "rev-parse", "--short", "HEAD")
    results, all_green = [], True
    for i, entry in enumerate(commands, 1):
        print(
            f"yt_gate: [{i}/{len(commands)}] {entry['command']}",
            file=sys.stderr,
            flush=True,
        )
        r = run_command(entry, root, env, args.timeout)
        # AC3: a policy block is reported distinctly from a plain code failure,
        # but it is still a FAIL for the purpose of all_green below (AC4).
        if r["policy_block"]:
            status = f"POLICY BLOCK (environment, exit {r['exit_code']})"
        elif r["exit_code"] == 0:
            status = "PASS"
        else:
            status = f"FAIL ({r['exit_code']})"
        print(f"yt_gate:   -> {status}", file=sys.stderr, flush=True)
        all_green = all_green and r["exit_code"] == 0
        results.append(r)

    fragment = emit_yaml(results, commit)
    print(fragment)
    if args.record:
        if args.allow_dirty:
            # The script already declares an --allow-dirty run non-evidence. Filing
            # one anyway would put a result stamped with a commit into the record
            # that the commit never produced -- dirty-tree-green, which is the exact
            # failure the gate exists to make impossible. Refusing here is cheaper
            # than a rule asking anyone to remember not to.
            print(
                "yt_gate: --record ignored: an --allow-dirty run is not valid DoD "
                "evidence, so it is not recorded. Commit, then re-run to record.",
                file=sys.stderr,
            )
        else:
            batch_path = Path(args.dod).parent / "batch.yaml" if args.dod else root / ".yourteam" / "batch.yaml"
            print(f"yt_gate: {record_evidence(batch_path, args.record, results, commit)}", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(fragment, encoding="utf-8")

    policy_blocked = [r for r in results if r["policy_block"]]
    if policy_blocked:
        print(
            f"yt_gate: POLICY BLOCK — {len(policy_blocked)} command(s) look like an "
            "environment block (a Windows Device Guard / Application Control policy), "
            "not a code failure:",
            file=sys.stderr,
        )
        for r in policy_blocked:
            print(
                f"yt_gate:   POLICY BLOCK: {r['command']} (exit {r['exit_code']})",
                file=sys.stderr,
            )
        print(f"yt_gate: {POLICY_BLOCK_PROOF_NOTE}", file=sys.stderr)

    if not all_green:
        print(
            "yt_gate: RED. If you suspect resource contention: prove it (empty diff since the "
            "batch cut AND passes with --only in isolation) before discounting — agreement "
            "2026-07-06.",
            file=sys.stderr,
        )
    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
