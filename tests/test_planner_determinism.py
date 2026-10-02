import os
import subprocess
import sys
from pathlib import Path

from app.planner.options import options
from app.planner.plan import canonical_json, plan
from tests.planner_fixtures import worked_example

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (
    "import sys\n"
    "from app.planner.options import options\n"
    "from app.planner.plan import canonical_json, plan\n"
    "from tests.planner_fixtures import worked_example\n"
    "s = worked_example(); r = plan(s)\n"
    "sys.stdout.buffer.write(canonical_json([r, options(s, r)]))\n"
)


def test_plan_twice_gives_identical_bytes():
    s = worked_example()
    assert canonical_json(plan(s)) == canonical_json(plan(s))
    r = plan(s)
    assert canonical_json(options(s, r)) == canonical_json(options(s, plan(s)))


def _run_with_hash_seed(seed: str) -> bytes:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    return subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, check=True
    ).stdout


def test_output_is_byte_identical_across_processes_with_different_hash_seeds():
    one, two = _run_with_hash_seed("1"), _run_with_hash_seed("2")
    assert one == two
    s = worked_example()
    r = plan(s)
    assert one == canonical_json([r, options(s, r)])


def test_canonical_json_refuses_floats():
    import pytest

    with pytest.raises(TypeError):
        canonical_json({"amount": 1.5})
