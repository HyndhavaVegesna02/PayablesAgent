"""One request timeout for every harness in a live ablation (CHG-044). Live,
the bare harness's growing chat history ran past Gemini's deadline at
config.yaml's 60 s and those runs went unscored; the ablation now gives every
harness the same longer timeout, and its header says so. The suite runner and
the workflow runs keep config.yaml's."""

import pytest

from evals import ablation, budget


@pytest.mark.parametrize("module, argv, timeout", [
    ("evals.ablation", ["--harness", "bare"], ablation.TIMEOUT_MS),
    ("evals.runner", ["--runs", "1", "--scenario", "01-debit-alert-for-a-planned-payment"], None),
    ("evals.workflow", ["--run", "A"], None),
])
def test_the_ablation_alone_sets_one_timeout_for_every_harness(module, argv, timeout, monkeypatch, tmp_path):
    seen = {}

    def fake_live_backend(app_config, *, confirmed, max_micro_usd=budget.MAX_MICRO_USD, timeout_ms=None):
        seen["timeout_ms"] = timeout_ms
        raise SystemExit("stop before any call")

    monkeypatch.setattr(budget, "live_backend", fake_live_backend)
    main = __import__(module, fromlist=["main"]).main
    with pytest.raises(SystemExit, match="stop before any call"):
        main(["--ai", "live", "--yes-spend", *argv, "--out", str(tmp_path)])
    assert seen == {"timeout_ms": timeout}


def test_the_timeout_is_long_enough_and_the_header_says_it_is_the_same_for_all():
    assert ablation.TIMEOUT_MS >= 3 * 60_000
    assert f"one request timeout, {ablation.TIMEOUT_MS // 1000} seconds" in ablation.FAIRNESS
