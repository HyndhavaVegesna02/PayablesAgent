"""Static guard for CLAUDE.md's standing invariant: "All code reads time
through app/clock.py's Clock interface." Added after the batch-0 review
caught app/jobs/queue.py calling datetime.now() directly -- this makes the
rule mechanically enforced instead of relying on review catching it again."""

import ast
from pathlib import Path

# Only the datetime module's own now()/today() are forbidden -- a Clock
# instance's .now()/.today() (e.g. self.clock.now()) is exactly how code is
# supposed to read time, and must not be flagged.
APP_DIR = Path(__file__).resolve().parent.parent / "app"
FORBIDDEN_RECEIVERS = {"datetime", "date"}
FORBIDDEN_ATTRS = {"now", "today"}


def _violations() -> list[str]:
    violations = []
    for path in APP_DIR.rglob("*.py"):
        if path.resolve() == (APP_DIR / "clock.py").resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_ATTRS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in FORBIDDEN_RECEIVERS
            ):
                violations.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
    return violations


def test_no_direct_datetime_now_or_date_today_outside_clock_py():
    violations = _violations()
    assert violations == [], (
        "direct .now()/.today() calls outside app/clock.py (route through "
        "the Clock interface instead): " + ", ".join(violations)
    )


def test_detector_does_not_flag_a_clock_instance_method(tmp_path):
    # Regression guard for the detector itself: the first version of this
    # check flagged `self.clock.now()` in app/trace/tracer.py as a false
    # positive, because it matched on method name alone.
    source = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        return self.clock.now()\n"
    )
    tree = ast.parse(source)
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in FORBIDDEN_ATTRS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in FORBIDDEN_RECEIVERS
    ]
    assert hits == []


def test_detector_flags_a_real_datetime_now_call():
    # `from datetime import datetime` + `datetime.now()` is the style used
    # everywhere in this codebase (e.g. the queue.py bug this test guards
    # against), so that's what the detector must actually catch.
    source = "from datetime import datetime\n\ndef bar():\n    return datetime.now()\n"
    tree = ast.parse(source)
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in FORBIDDEN_ATTRS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in FORBIDDEN_RECEIVERS
    ]
    assert len(hits) == 1
