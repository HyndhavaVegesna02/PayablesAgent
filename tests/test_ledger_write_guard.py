"""Static guard for "only app/ledger/writer.py writes ledger tables" (batch 1
plan, D4 and D10). Works like the datetime.now guard: it parses every module
and fails on any SQL string literal that writes a guarded table. Known limit:
SQL whose table name is a runtime variable (f"UPDATE {t}") is not caught."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("app", "fixtures", "evals")
WRITER = ROOT / "app" / "ledger" / "writer.py"

# path (relative to the repo root) -> why it may write a guarded table
ALLOW_LIST: dict[str, str] = {
    "evals/bare.py": "the ablation's bare harness is the system without a ledger writer, by design; it writes only "
                     "its own scratch copy of the seeded database (CHG-010a S6, D24)",
}

_TABLE_PREFIX = r"\s+[\"`\[]?"
LEDGER_WRITE = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)"
    + _TABLE_PREFIX
    + r"(payable|receivable|bank_txn|tax_obligation|event|plan_override)\b",
    re.IGNORECASE,
)
# D10: bank_account's drift_status / reported balance are ledger state; creating
# an account (setup, seed) stays allowed, changing or removing one does not.
BANK_ACCOUNT_CHANGE = re.compile(
    r"\b(?:UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)" + _TABLE_PREFIX + r"(bank_account)\b",
    re.IGNORECASE,
)


def _string_literals(tree: ast.AST):
    # An f-string's literal pieces are Constant nodes too; read them once, joined.
    inside_fstrings = {
        id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values
    }
    for node in ast.walk(tree):
        if id(node) in inside_fstrings:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value if isinstance(v, ast.Constant) else "{}" for v in node.values
            )
            yield node.lineno, text


def guarded_writes(source: str) -> list[tuple[int, str]]:
    hits = []
    for lineno, text in _string_literals(ast.parse(source)):
        for pattern in (LEDGER_WRITE, BANK_ACCOUNT_CHANGE):
            for m in pattern.finditer(text):
                hits.append((lineno, m.group(1).lower()))
    return hits


def _violations() -> list[str]:
    found = []
    for d in SCANNED_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")) if (ROOT / d).exists() else []:
            if path.resolve() == WRITER.resolve():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOW_LIST:
                continue
            for lineno, table in guarded_writes(path.read_text(encoding="utf-8")):
                found.append(f"{rel}:{lineno} writes {table}")
    return found


def test_only_the_ledger_writer_writes_ledger_tables():
    violations = _violations()
    assert violations == [], (
        "ledger tables may only be written by app/ledger/writer.py "
        "(add an ALLOW_LIST entry with a reason if this is deliberate): " + "; ".join(violations)
    )


def test_every_allow_list_entry_has_a_reason():
    assert all(reason.strip() for reason in ALLOW_LIST.values())


# --- the detector itself ------------------------------------------------------


def test_detector_flags_a_multiline_insert():
    src = 'conn.execute("""\n    INSERT INTO\n      payable (business_id) VALUES (1)\n""")\n'
    assert guarded_writes(src) == [(1, "payable")]


def test_detector_flags_update_or_ignore_and_quoted_names():
    src = (
        'a = "UPDATE OR IGNORE bank_txn SET status = 1"\n'
        'b = "delete from \\"event\\" where id = 1"\n'
        'c = "REPLACE INTO receivable VALUES (1)"\n'
        'd = f"INSERT INTO tax_obligation ({cols}) VALUES (1)"\n'
    )
    assert [t for _, t in guarded_writes(src)] == ["bank_txn", "event", "receivable", "tax_obligation"]


def test_detector_flags_bank_account_changes_but_not_creation():
    src = (
        'a = "UPDATE bank_account SET drift_status = \'CHECKING\'"\n'
        'b = "DELETE FROM bank_account WHERE id = 1"\n'
        'c = "INSERT INTO bank_account (id) VALUES (1)"\n'
    )
    assert guarded_writes(src) == [(1, "bank_account"), (2, "bank_account")]


def test_detector_ignores_reads_other_tables_and_triggers():
    src = (
        'a = "SELECT * FROM payable WHERE status = \'PAID\'"\n'
        'b = "UPDATE job SET status = \'done\'"\n'
        'c = "CREATE TRIGGER event_no_update BEFORE UPDATE ON event BEGIN SELECT 1; END"\n'
        'd = "INSERT INTO payable_archive VALUES (1)"\n'
        'e = "SELECT * FROM bank_account"\n'
    )
    assert guarded_writes(src) == []
