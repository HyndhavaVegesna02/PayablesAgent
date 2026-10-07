"""Runs a command with a demo profile's settings as process environment
(CHG-058): `python scripts/with_env.py FILE [FILE ...] [KEY=VALUE ...] -- COMMAND ...`.

Each FILE holds KEY=VALUE lines (blank lines and # comments skipped); a later
file, then a KEY=VALUE argument, overrides an earlier one. Settings reads the
process environment before .env, so these values win for this command only,
and .env is neither read nor touched here: the API key and the session secret
stay there. A file or argument that names a secret is refused, so a profile
committed to the repo can't carry one."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SECRETS = {"GEMINI_API_KEY", "SESSION_SECRET", "FERNET_KEY", "GOOGLE_CLIENT_SECRET", "SMTP_PASSWORD"}


class Refused(Exception):
    pass


def parse(lines: list[str], where: str) -> dict[str, str]:
    out = {}
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, eq, value = line.partition("=")
        key = key.strip()
        if not eq or not key.isidentifier():
            raise Refused(f"{where}:{n}: not KEY=VALUE: {line!r}")
        if key.upper() in SECRETS:
            raise Refused(f"{where}:{n}: {key} is a secret; it belongs in .env only")
        out[key.upper()] = value.strip()
    return out


def environment(args: list[str]) -> dict[str, str]:
    """The settings the arguments before `--` give, in order."""
    values: dict[str, str] = {}
    for arg in args:
        if "=" in arg and not Path(arg).is_file():
            values.update(parse([arg], "argument"))
        else:
            values.update(parse(Path(arg).read_text(encoding="utf-8").splitlines(), arg))
    return values


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--" not in argv or argv.index("--") == 0 or argv.index("--") == len(argv) - 1:
        print("usage: python scripts/with_env.py FILE [FILE ...] [KEY=VALUE ...] -- COMMAND ...", file=sys.stderr)
        return 2
    cut = argv.index("--")
    try:
        values = environment(argv[:cut])
    except (Refused, OSError) as e:
        print(f"with_env: {e}", file=sys.stderr)
        return 2
    command = argv[cut + 1:]
    if command[0] == "python":  # this interpreter: the project's virtualenv under `uv run`
        command = [sys.executable, *command[1:]]
    return subprocess.call(command, env={**os.environ, **values})


if __name__ == "__main__":
    sys.exit(main())
