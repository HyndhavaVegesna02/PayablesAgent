from app.planner.diff import Change, diff
from app.planner.options import options
from app.planner.plan import AccountCash, PayableIn, plan
from tests.planner_fixtures import oct, snapshot, worked_example


def _nandi_pays_early():
    s = worked_example()
    return plan(s), options(s, plan(s))[0].plan


def test_golden_diff_when_nandi_pays_early():
    before, after = _nandi_pays_early()
    d = diff(before, after)
    assert d.changes == (
        Change("lowest", None, {"amount_paise": 18_300_000, "on": oct(22)},
               {"amount_paise": 38_300_000, "on": oct(22)}),
        Change("validity", None, {"valid": False}, {"valid": True}),
        Change("line_changed", 5,
               {"decision": "ESCALATE", "pay_on": None, "amount_paise": 12_000_000},
               {"decision": "PAY", "pay_on": oct(22), "amount_paise": 12_000_000}),
    )


def test_the_explain_check_allow_lists_are_exactly_what_the_changes_mention():
    d = diff(*_nandi_pays_early())
    assert d.amounts_paise == {18_300_000, 38_300_000, 12_000_000}
    assert d.dates == {oct(22)}


def test_identical_plans_have_an_empty_diff():
    r = plan(worked_example())
    d = diff(r, plan(worked_example()))
    assert (d.changes, d.amounts_paise, d.dates) == ((), frozenset(), frozenset())


def test_added_removed_and_opening_cash_changes():
    old = plan(snapshot(payables=(PayableIn(1, 100, oct(14), "normal"),)))
    new = plan(snapshot(payables=(PayableIn(2, 300, oct(15), "normal"),),
                        accounts=(AccountCash(1, 100_000_500, None, False),)))
    d = diff(old, new)
    assert [(c.kind, c.payable_id) for c in d.changes] == [
        ("opening_cash", None), ("lowest", None), ("line_removed", 1), ("line_added", 2),
    ]
    assert d.amounts_paise == {100_000_000, 100_000_500, 99_999_900, 100_000_200, 100, 300}
    assert d.dates == {oct(12), oct(15)}
