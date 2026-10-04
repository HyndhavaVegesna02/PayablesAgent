"""A cost cap per live invocation (CHG-041). `--max-usd` is read as text to
integer micro-USD (no float holds money) and can only lower the guard's hard
$5 cap; each eval CLI hands it to the invocation's one BudgetGuard."""

import argparse

import pytest

from evals import budget
from evals.budget import MAX_MICRO_USD, BudgetGuard, usd_cap
from tests.test_evals import CONFIG, Priced


@pytest.mark.parametrize("text, micro", [("2", 2_000_000), ("1.50", 1_500_000), ("0.75", 750_000),
                                         ("0.5", 500_000), ("5", 5_000_000), ("$1.25", 1_250_000)])
def test_dollars_read_to_integer_micro_usd(text, micro):
    assert usd_cap(text) == micro and type(usd_cap(text)) is int


@pytest.mark.parametrize("text", ["5.01", "0", "-1", "abc", "1.2345678", "", "1e3"])
def test_a_cap_above_the_hard_cap_or_unreadable_is_refused(text):
    with pytest.raises(argparse.ArgumentTypeError):
        usd_cap(text)


def test_the_guard_stops_at_the_lower_cap():
    one = __import__("app.ai.client", fromlist=["RawAIResponse"]).RawAIResponse("{}", 1_000_000, 0, 0)  # 750,000
    g = BudgetGuard(Priced(one, one, one), CONFIG, max_micro_usd=1_500_000, sleep=lambda s: None, delay_s=0)
    g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    with pytest.raises(Exception):  # 750,000 spent + 750,000 dearest = 1.5M: allowed; then stop
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
        g.generate(model="m", system="s", contents="c", thinking="low", json_schema=None)
    assert "cost cap reached" in g.should_stop() and g.summary()["caps"]["micro_usd"] == 1_500_000


@pytest.mark.parametrize("module, argv", [
    ("evals.runner", ["--ai", "live", "--yes-spend", "--runs", "1", "--scenario", "01-debit-alert-for-a-planned-payment"]),
    ("evals.ablation", ["--ai", "live", "--yes-spend", "--harness", "full"]),
    ("evals.workflow", ["--ai", "live", "--yes-spend", "--run", "A"]),
])
def test_each_cli_hands_the_cap_to_its_one_guard(module, argv, monkeypatch, tmp_path):
    seen = {}

    def fake_live_backend(app_config, *, confirmed, max_micro_usd=MAX_MICRO_USD):
        seen.update(confirmed=confirmed, max_micro_usd=max_micro_usd)
        raise SystemExit("stop before any call")

    monkeypatch.setattr(budget, "live_backend", fake_live_backend)
    main = __import__(module, fromlist=["main"]).main
    with pytest.raises(SystemExit, match="stop before any call"):
        main([*argv, "--max-usd", "1.50", "--out", str(tmp_path)])
    assert seen == {"confirmed": True, "max_micro_usd": 1_500_000}
    seen.clear()
    with pytest.raises(SystemExit, match="stop before any call"):
        main([*argv, "--out", str(tmp_path)])
    assert seen["max_micro_usd"] == MAX_MICRO_USD  # no flag: the hard cap
