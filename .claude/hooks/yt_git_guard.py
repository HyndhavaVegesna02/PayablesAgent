#!/usr/bin/env python3
"""YourTeam git-discipline guard.

PreToolUse hook for Bash/PowerShell. During an ACTIVE batch it blocks, with
exit code 2 (stderr is fed back to the agent):

  1. Bulk staging — `git add -A`, `git add --all`, `git add .`
     (working agreement 2026-06-24: an uncommitted orchestrator edit was once
     swept into a story commit by `git add -A`).
  2. `git commit` on any branch other than the batch branch or hotfix/*
     (edge-case #12: a silently failed checkout once put a whole story on
     the default branch).

Outside an active batch (no .yourteam/, or status != active) it allows
everything. It FAILS OPEN: any internal error allows the call — this guard
is a backstop, never an outage.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

BULK_ADD_RE = re.compile(
    r"\bgit\s+add\s+(?:[^;&|]*\s)?(-A\b|--all\b|\.(?=\s*(?:$|[;&|])))"
)
COMMIT_RE = re.compile(r"\bgit\s+commit\b")


def find_root(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / ".yourteam").is_dir():
            return p
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        if "git" not in command:
            return 0
        root = find_root(Path(data.get("cwd") or Path.cwd()).resolve())
        if root is None:
            return 0
        batch_file = root / ".yourteam" / "batch.yaml"
        if not batch_file.exists():
            return 0
        text = batch_file.read_text(encoding="utf-8", errors="replace")
        status = re.search(r"^status:\s*(\S+)", text, re.M)
        if not status or status.group(1) != "active":
            return 0
        branch_m = re.search(r"^branch:\s*(\S+)", text, re.M)
        batch_branch = branch_m.group(1) if branch_m else None

        if BULK_ADD_RE.search(command):
            print(
                "YourTeam guard: bulk staging (git add -A/--all/.) is blocked during an active "
                "batch — stage only the files this step changed (R003).",
                file=sys.stderr,
            )
            return 2

        if batch_branch and COMMIT_RE.search(command):
            cur = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            if cur and cur != batch_branch and not cur.startswith("hotfix/"):
                print(
                    f"YourTeam guard: batch '{batch_branch}' is active but the current branch "
                    f"is '{cur}'. Commits belong on the batch branch (or hotfix/*). Stop and "
                    "repair the branch state first (edge-case #12); do not commit here.",
                    file=sys.stderr,
                )
                return 2
        return 0
    except Exception:
        return 0  # fail open — a broken guard must never block real work


if __name__ == "__main__":
    sys.exit(main())
