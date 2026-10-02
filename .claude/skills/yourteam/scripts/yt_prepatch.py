#!/usr/bin/env python3
"""Pre-patch test gate.

A test that passes without the change is not testing the change. This script
replays the tests a change added or modified against the tree as it was BEFORE
the change, and requires them to FAIL there.

It catches the expensive class of test defects mechanically, with no judgment
and no model in the loop:

  * a test that names one scenario and exercises a different, already-passing
    path (a "rigged" test)
  * assertions that cannot fail (testing a mock, vacuous asserts, disabled body)
  * coverage deleted and replaced with something that never exercised the change
  * a test written after the fact against code that already worked

How it works: a detached worktree is created at the change's start commit, the
change's test files are copied in from HEAD, and the project's test command runs
there. Nonzero (including a collection or import error, which is a legitimate
pre-patch failure -- the code genuinely was not there yet) means the tests
depend on the change. Exit 0 means the gate PASSED.

Config is read from .yourteam/config.yaml (plain `key: value` lines, no YAML
dependency):

    test_glob: tests/**/*.py,**/*_test.py,**/test_*.py
    test_command: python -m pytest {files}
    default_branch: main

`{files}` is replaced with the space-joined relative paths of the changed test
files. If the command contains no `{files}`, it runs unmodified (whole suite).

Usage:
  yt_prepatch.py --since <commit>            # gate the range <commit>..HEAD
  yt_prepatch.py --since <commit> --list     # show what would run, run nothing
  yt_prepatch.py --since <commit> --to <ref> # explicit end of range

Exit codes:
  0  gate passed (tests failed pre-patch, as required), or no test files changed
  1  gate FAILED (tests passed pre-patch -- they do not depend on the change)
  2  could not run (bad ref, no config, worktree failure)
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TEST_GLOB = "tests/**,**/test_*.py,**/*_test.py,**/*.test.*,**/*.spec.*"
DEFAULT_TEST_COMMAND = "python -m pytest {files}"


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def repo_root() -> Path:
    proc = run(["git", "rev-parse", "--show-toplevel"])
    if proc.returncode != 0:
        sys.stderr.write("not inside a git repository\n")
        raise SystemExit(2)
    return Path(proc.stdout.strip())


def read_config(root: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    path = root / ".yourteam" / "config.yaml"
    if not path.exists():
        return cfg
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        cfg[key.strip()] = value.strip().strip("'\"")
    return cfg


def matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # `tests/**` should also match `tests/foo.py`, which fnmatch misses.
        if pattern.endswith("/**") and path.startswith(pattern[:-2]):
            return True
    return False


def changed_test_files(root: Path, since: str, to: str, patterns: list[str]) -> list[str]:
    proc = run(["git", "diff", "--name-only", "--diff-filter=d", f"{since}..{to}"], cwd=root)
    if proc.returncode != 0:
        sys.stderr.write(f"could not diff {since}..{to}: {proc.stderr.strip()}\n")
        raise SystemExit(2)
    files = [f for f in proc.stdout.splitlines() if f.strip()]
    return [f for f in files if matches_any(f, patterns)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Require a change's tests to fail before the change.")
    parser.add_argument("--since", required=True, help="the change's start commit")
    parser.add_argument("--to", default="HEAD", help="end of the range (default HEAD)")
    parser.add_argument("--list", action="store_true", help="show what would run, run nothing")
    args = parser.parse_args()

    root = repo_root()
    cfg = read_config(root)
    patterns = [p.strip() for p in cfg.get("test_glob", DEFAULT_TEST_GLOB).split(",") if p.strip()]
    command = cfg.get("test_command", DEFAULT_TEST_COMMAND)

    for ref in (args.since, args.to):
        if run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=root).returncode != 0:
            sys.stderr.write(f"not a commit: {ref}\n")
            return 2

    tests = changed_test_files(root, args.since, args.to, patterns)
    if not tests:
        print("PASS: no test files changed in range -- nothing to replay.")
        print("      (If this change should have added tests, that is a review finding, not a gate one.)")
        return 0

    files_arg = " ".join(tests)
    shell_cmd = command.replace("{files}", files_arg) if "{files}" in command else command

    if args.list:
        print(f"range:   {args.since}..{args.to}")
        print("tests:   " + "\n         ".join(tests))
        print(f"command: {shell_cmd}")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="yt-prepatch-"))
    worktree = tmp / "tree"
    added = run(["git", "worktree", "add", "--detach", str(worktree), args.since], cwd=root)
    if added.returncode != 0:
        sys.stderr.write(f"could not create worktree: {added.stderr.strip()}\n")
        shutil.rmtree(tmp, ignore_errors=True)
        return 2

    try:
        for rel in tests:
            src = root / rel
            dst = worktree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        proc = subprocess.run(shell_cmd, cwd=worktree, shell=True, capture_output=True, text=True)
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]

        print(f"range:   {args.since}..{args.to}")
        print(f"tests:   {len(tests)} file(s) replayed against the pre-change tree")
        print(f"command: {shell_cmd}")
        print(f"exit:    {proc.returncode}")
        if tail:
            print("--- output tail ---")
            print("\n".join(tail))
            print("-------------------")

        if proc.returncode != 0:
            print("\nPASS: the tests fail without the change, so they depend on it.")
            return 0

        print(
            "\nFAIL: these tests PASS without the change.\n"
            "      They are not exercising what the change did. Before anything else, read each\n"
            "      test body and check it against the acceptance criterion it claims to cover --\n"
            "      the usual causes are a scenario that takes an already-working path, an\n"
            "      assertion that cannot fail, or a mock standing in for the thing under test."
        )
        return 1
    finally:
        run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
