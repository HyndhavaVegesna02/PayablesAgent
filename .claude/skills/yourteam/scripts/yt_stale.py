#!/usr/bin/env python3
"""Knowledge-note staleness, as git arithmetic.

A note is stale when any path it covers changed after the note's own last
commit. The baseline is derived, never stored, so there is no stamp to bump
and no commit whose only purpose is repairing one. A commit that touches a
note and its covered path together is trivially not stale.

Notes live in docs/notes/ with frontmatter:

    ---
    covers: [src/auth/, src/middleware/session.py]
    ---

Untracked or uncommitted notes have no baseline, so they are reported as NEW
and treated as fresh -- you just wrote them.

Usage:
  yt_stale.py                       # report every note
  yt_stale.py --brief <path>...     # print only FRESH notes covering those paths
  yt_stale.py --check               # exit 1 if any note is stale

`--brief` is the reverse-blast-radius lookup: given the paths a change will
touch, it returns the notes worth quoting into a dispatch brief. Stale notes
are quarantined -- readable by you, never quoted -- so the worst case degrades
to "no notes, go read the code", never to confidently wrong.

Exit codes: 0 ok; 1 stale notes exist (--check only); 2 could not run.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

NOTES_DIR = "docs/notes"
COVERS_RE = re.compile(r"^covers:\s*\[?(.*?)\]?\s*$", re.MULTILINE)


def git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def repo_root() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write("not inside a git repository\n")
        raise SystemExit(2)
    return Path(proc.stdout.strip())


def covered_paths(note: Path) -> list[str]:
    text = note.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    front = text[:end] if end != -1 else text[:2000]
    match = COVERS_RE.search(front)
    if not match:
        return []
    return [p.strip().strip("'\"") for p in match.group(1).split(",") if p.strip()]


def status(root: Path, note: Path) -> tuple[str, list[str]]:
    """Return (FRESH | STALE | NEW | UNSCOPED, paths that moved)."""
    rel = note.relative_to(root).as_posix()
    paths = covered_paths(note)
    if not paths:
        return "UNSCOPED", []
    baseline = git(["log", "-1", "--format=%H", "--", rel], cwd=root)
    if not baseline:
        return "NEW", []
    moved = git(["diff", "--name-only", f"{baseline}..HEAD", "--", *paths], cwd=root)
    changed = [line for line in moved.splitlines() if line.strip()]
    return ("STALE", changed) if changed else ("FRESH", [])


def overlaps(covered: list[str], targets: list[str]) -> bool:
    for c in covered:
        for t in targets:
            if t.startswith(c) or c.startswith(t):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Report knowledge-note staleness.")
    parser.add_argument("--brief", nargs="+", metavar="PATH", help="print only fresh notes covering these paths")
    parser.add_argument("--check", action="store_true", help="exit 1 if any note is stale")
    parser.add_argument("--dir", default=NOTES_DIR, help=f"notes directory (default {NOTES_DIR})")
    args = parser.parse_args()

    root = repo_root()
    notes_dir = root / args.dir
    if not notes_dir.exists():
        print(f"no notes directory at {args.dir} -- nothing to check.")
        return 0

    notes = sorted(p for p in notes_dir.rglob("*.md") if "archive" not in p.relative_to(notes_dir).parts)
    stale_found = False

    for note in notes:
        state, moved = status(root, note)
        rel = note.relative_to(root).as_posix()
        if state == "STALE":
            stale_found = True

        if args.brief:
            if state in ("FRESH", "NEW") and overlaps(covered_paths(note), args.brief):
                print(f"=== {rel} ===")
                print(note.read_text(encoding="utf-8", errors="replace").strip())
                print()
            continue

        line = f"{state:9} {rel}"
        if state == "STALE":
            line += f"  <- changed since: {', '.join(moved[:4])}" + (" ..." if len(moved) > 4 else "")
        if state == "UNSCOPED":
            line += "  <- no `covers:` frontmatter; it asserts nothing checkable"
        print(line)

    if args.brief:
        return 0
    if stale_found:
        print("\nStale notes are readable but quarantined: never quote one into a dispatch brief.")
        print("Editing a note is what re-verifies it, so re-read the code before you touch it.")
    return 1 if (args.check and stale_found) else 0


if __name__ == "__main__":
    raise SystemExit(main())
