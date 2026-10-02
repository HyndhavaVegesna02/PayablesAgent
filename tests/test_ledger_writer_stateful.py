"""Part 1's invariant "a PAID bill never disappears; it is PAID or REOPENED",
checked against the real writer on a real SQLite file (batch 1 plan, D5)."""

import tempfile
from datetime import date
from pathlib import Path

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

from app.domain.states import PAYABLE_STATES, PAYABLE_TRANSITIONS, TransitionRefused, parse_actor
from app.ledger import writer
from app.ledger.writer import EntityRef
from tests.ledger_helpers import make_ledger_db, payable_new

ACTORS = ["owner:1", "planner", "reconciler", "pipeline", "agent:case:1"]
REACHED_PAID: list[bool] = []


class LedgerMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self._dir = tempfile.TemporaryDirectory()
        self.conn = make_ledger_db(Path(self._dir.name) / "stateful.db")
        self.ids: list[int] = []
        self.last_status: dict[int, str] = {}
        self.expected_events = 0
        self.reached_paid = False

    def teardown(self):
        REACHED_PAID.append(self.reached_paid)
        self.conn.close()
        self._dir.cleanup()

    def _row(self, pid):
        return self.conn.execute(
            "SELECT status, version FROM payable WHERE id = ?", (pid,)
        ).fetchone()

    def _event_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]

    @rule()
    def create(self):
        p = writer.create_payable(payable_new(), actor="pipeline", reason="t", source_ref=None,
                                  conn=self.conn)
        self.ids.append(p.id)
        self.expected_events += 1

    @precondition(lambda self: self.ids)
    @rule(data=st.data(), to=st.sampled_from(PAYABLE_STATES), actor=st.sampled_from(ACTORS),
          stale=st.booleans())
    def attempt_transition(self, data, to, actor, stale):
        pid = data.draw(st.sampled_from(self.ids))
        before = tuple(self._row(pid))
        events_before = self._event_count()
        fields = {"planned_date": date(2026, 10, 22)} if to == "PLANNED" else None
        try:
            writer.transition(EntityRef("payable", pid), to, actor, "t", None, conn=self.conn,
                              expected_version=before[1] + (1 if stale else 0), fields=fields)
        except TransitionRefused:
            assert tuple(self._row(pid)) == before
            assert self._event_count() == events_before
            return
        role = parse_actor(actor).role
        assert role in PAYABLE_TRANSITIONS[(before[0], to)]
        assert not stale
        assert tuple(self._row(pid)) == (to, before[1] + 1)
        self.expected_events += 1

    @rule()
    def pay_a_new_bill(self):
        # Walks one bill DRAFT -> PAID through the writer, so later random
        # attempts are made against bills that really are PAID.
        p = writer.create_payable(payable_new(), actor="pipeline", reason="t", source_ref=None,
                                  conn=self.conn)
        self.ids.append(p.id)
        ref = EntityRef("payable", p.id)
        for to, actor, fields in (
            ("CONFIRMED", "owner:1", None),
            ("PLANNED", "planner", {"planned_date": date(2026, 10, 22)}),
            ("PAYMENT_EXPECTED", "owner:1", None),
            ("PAID", "reconciler", None),
        ):
            p = writer.transition(ref, to, actor, "t", None, conn=self.conn,
                                  expected_version=p.version, fields=fields)
        self.expected_events += 5
        self.reached_paid = True

    @precondition(lambda self: self.ids)
    @rule(data=st.data())
    def advance_legally(self, data):
        # Random attempts alone almost never chain four legal moves, so the PAID
        # invariant would go untested; this rule walks a legal edge each time.
        pid = data.draw(st.sampled_from(self.ids))
        status, version = tuple(self._row(pid))
        moves = sorted(
            (to, role) for (frm, to), roles in PAYABLE_TRANSITIONS.items()
            if frm == status and to != "SPLIT" for role in roles
        )
        if not moves:
            return
        to, role = data.draw(st.sampled_from(moves))
        actor = "owner:1" if role == "owner" else role
        fields = {"planned_date": date(2026, 10, 22)} if to == "PLANNED" else None
        writer.transition(EntityRef("payable", pid), to, actor, "t", None, conn=self.conn,
                          expected_version=version, fields=fields)
        self.expected_events += 1
        if to == "PAID":
            self.reached_paid = True

    @precondition(lambda self: self.ids)
    @rule(data=st.data(), actor=st.sampled_from(ACTORS),
          first=st.integers(min_value=-1, max_value=12_000_001))
    def attempt_split(self, data, actor, first):
        pid = data.draw(st.sampled_from(self.ids))
        before = tuple(self._row(pid))
        events_before = self._event_count()
        try:
            a, b = writer.split_payable(EntityRef("payable", pid), first, date(2026, 10, 26), actor,
                                        "t", None, conn=self.conn, expected_version=before[1])
        except (TransitionRefused, ValueError):
            assert tuple(self._row(pid)) == before
            assert self._event_count() == events_before
            return
        assert before[0] in ("CONFIRMED", "PLANNED")
        self.ids += [a.id, b.id]
        self.expected_events += 3

    @invariant()
    def rows_are_never_deleted(self):
        count = self.conn.execute("SELECT COUNT(*) FROM payable").fetchone()[0]
        assert count == len(self.ids)
        for pid in self.ids:
            assert self._row(pid) is not None

    @invariant()
    def paid_only_leaves_to_reopened(self):
        for pid in self.ids:
            now = self._row(pid)[0]
            if self.last_status.get(pid) == "PAID":
                assert now in ("PAID", "REOPENED"), (pid, now)
            self.last_status[pid] = now

    @invariant()
    def every_successful_write_left_exactly_one_event(self):
        assert self._event_count() == self.expected_events


def test_paid_never_disappears_over_random_transition_sequences():
    REACHED_PAID.clear()
    run_state_machine_as_test(
        LedgerMachine, settings=settings(max_examples=50, stateful_step_count=30, deadline=None)
    )
    assert any(REACHED_PAID), "no run reached PAID, so the PAID invariant was never exercised"
