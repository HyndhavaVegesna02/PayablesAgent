"""app/validate is pure (batch 5 plan, S1; PO requirement): the rule checks
take plain values and do no I/O. import-linter holds the app-internal half
("validate is pure: imports only domain"); this AST scan holds the standard
library half, which import-linter does not see."""

import ast
from pathlib import Path

VALIDATE = Path(__file__).resolve().parent.parent / "app" / "validate"
NO_IO = {"sqlite3", "os", "pathlib", "socket", "httpx", "io", "subprocess", "shutil", "logging", "urllib", "requests"}


def imported(source: str) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def test_validate_modules_import_no_io_and_only_domain_from_app():
    bad = []
    for path in sorted(VALIDATE.glob("*.py")):
        for line, name in imported(path.read_text(encoding="utf-8")):
            top = name.split(".")[0]
            in_app_but_not_pure = top == "app" and not name.startswith(("app.domain", "app.validate"))
            if top in NO_IO or in_app_but_not_pure:
                bad.append(f"{path.name}:{line} imports {name}")
    assert bad == []


def test_the_scan_catches_what_it_should():
    assert imported("import sqlite3\nfrom app.clock import TIMEZONE\n") == [(1, "sqlite3"), (2, "app.clock")]
