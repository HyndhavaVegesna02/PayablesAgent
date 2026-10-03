"""Refreshes the generated tables in docs/permission-model.md (batch 7,
CHG-010c): the exception agent's tools, from their annotations
(app/agent/permissions.py), and who may call each web route, from the
routes' own `require(...)` dependencies. tests/test_evidence_docs.py runs
`--check`, so the page cannot say something the code does not.

    uv run python scripts/make_docs.py            # rewrite the generated blocks
    uv run python scripts/make_docs.py --check    # exit 1 if they are out of date"""

from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "permission-model.md"
ROUTES_BEGIN = "<!-- generated: scripts/make_docs.py routes -->"
ROUTES_END = "<!-- end generated routes -->"


def _api_routes(routes):
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def routes_table() -> str:
    from app.config import Settings
    from app.main import create_app

    def table(demo_now: str) -> dict[tuple[str, str], str]:
        with tempfile.TemporaryDirectory(prefix="make-docs-") as tmp:
            settings = Settings(_env_file=None, session_secret="docs-only", database_path=str(Path(tmp) / "x.db"),
                                data_dir=tmp, demo_now=demo_now)
            app = create_app(settings)
        found = {}
        for route in _api_routes(app.routes):
            roles = [d.call.roles for d in route.dependant.dependencies if hasattr(d.call, "roles")]
            for method in sorted(route.methods - {"HEAD"}):
                found[(route.path, method)] = ", ".join(roles[0]) if roles else "anyone (no login)"
        return found

    always = table("")
    in_demo = table("2026-10-12T09:00:00+05:30")
    rows = [(p, m, w) for (p, m), w in always.items()]
    rows += [(p, m, f"{w} (demo mode only: registered when DEMO_NOW is set)") for (p, m), w in in_demo.items()
             if (p, m) not in always]
    lines = [ROUTES_BEGIN, "| Method | Route | Who may call it |", "| --- | --- | --- |"]
    lines += [f"| {m} | `{p}` | {w} |" for p, m, w in sorted(rows)]
    lines.append(ROUTES_END)
    return "\n".join(lines)


def _blocks() -> list[tuple[str, str, str]]:
    from app.agent.permissions import BEGIN, END, table

    return [(BEGIN, END, table()), (ROUTES_BEGIN, ROUTES_END, routes_table())]


def refreshed(text: str) -> str:
    for begin, end, block in _blocks():
        pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
        if not pattern.search(text):
            raise ValueError(f"{PAGE.name} has no {begin} ... {end} block")
        text = pattern.sub(lambda _: block, text)
    return text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts/make_docs.py")
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    text = PAGE.read_text(encoding="utf-8")
    new = refreshed(text)
    if args.check:
        if new != text:
            print(f"{PAGE.relative_to(ROOT)} is out of date (run: uv run python scripts/make_docs.py)")
            return 1
        return 0
    PAGE.write_text(new, encoding="utf-8", newline="\n")
    print(f"refreshed {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
