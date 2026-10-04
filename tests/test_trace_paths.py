"""CHG-054: kept traces stay under Windows MAX_PATH. Live ablation v2's bare
harness and four knock-outs crashed copying their first run's traces: a deep
output folder, then traces/<harness>/<scenario name>-run<n>/<date>/<file>,
ran past 260 characters. The layout is shorter, and on Windows the copy uses
the long-path prefix."""

import os
from pathlib import Path

from evals import ablation
from evals import runner
from evals.runner import LONG_PREFIX, long_path


def test_an_ablation_keeps_traces_under_an_output_folder_past_260_characters(tmp_path):
    base = tmp_path / ("d" * max(1, 215 - len(str(tmp_path))))  # the report folder itself stays creatable
    ablation.main(["--ai", "fixtures", "--harness", "full", "--harness", "bare", "--scenario",
                   "06-payment-returned-by-the-bank", "--label", "t", "--keep-traces", "--out", str(base)])
    (out,) = base.glob("*-fixtures-t")
    deepest = 0
    for h in ("full", "bare"):  # traces/<harness>/<scenario number>-run<n>/<date>/<file>
        assert os.listdir(long_path(out / "traces" / h)) == ["06-run1"]
        files = [os.path.join(d, f) for d, _, fs in os.walk(long_path(out / "traces" / h / "06-run1")) for f in fs]
        assert files and all(f.endswith(".jsonl") for f in files)
        deepest = max(deepest, *(len(f.removeprefix(LONG_PREFIX)) for f in files))
    assert deepest > 260  # past MAX_PATH, and still copied


def test_long_path_is_the_path_itself_off_windows(monkeypatch):
    import types

    monkeypatch.setattr(runner, "os", types.SimpleNamespace(name="posix"))
    assert long_path("a/b") == str(Path("a/b").resolve())
