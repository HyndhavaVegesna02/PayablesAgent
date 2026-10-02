"""Moving the demo clock forward (batch 3 plan, PO decision D14):
`make demo-time T=2026-10-15T09:00:00+05:30`, or the owner's form on the
Settings page, which calls the same function. Only in demo mode (DEMO_NOW
set). Time never moves backwards, and moving past a Monday 07:00 enqueues
that Monday's plan, as the worker's real-time cron does outside a demo. Each
move also queues a mail poll, so newly released mail is read at once."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, time, timedelta

from app.clock import TIMEZONE, DemoClock
from app.jobs import queue

MONDAY_PLAN_AT = time(7, 0)


class NotADemo(RuntimeError):
    pass


def parse_time(text: str) -> datetime:
    """An ISO time; one without an offset is read as Asia/Kolkata."""
    at = datetime.fromisoformat(text.strip())
    return at if at.tzinfo is not None else at.replace(tzinfo=TIMEZONE)


def _mondays_crossed(before: datetime, after: datetime) -> list[datetime]:
    out = []
    day = before.astimezone(TIMEZONE).date()
    while day <= after.astimezone(TIMEZONE).date():
        at = datetime.combine(day, MONDAY_PLAN_AT, tzinfo=TIMEZONE)
        if day.weekday() == 0 and before < at <= after:
            out.append(at)
        day += timedelta(days=1)
    return out


def advance(conn: sqlite3.Connection, clock, to: datetime) -> datetime:
    """Sets the demo clock to `to` (forward only) and enqueues the Monday plan
    when a Monday 07:00 was crossed. Returns the new instant."""
    if not isinstance(clock, DemoClock):
        raise NotADemo("the clock only moves by hand in demo mode (set DEMO_NOW)")
    before = clock.set(to)
    if _mondays_crossed(before, clock.now()):
        queue.enqueue_monday_plans(conn, clock=clock)
    # Time passed, so the mail polls that would have run did: one poll now picks
    # up whatever the new time releases, without waiting for the real-time interval.
    if queue.queued_job_id(conn, "poll_mail") is None:
        queue.enqueue(conn, kind="poll_mail", payload={}, clock=clock)
    conn.commit()
    return clock.now()


def main(argv: list[str] | None = None) -> int:
    from app.clock import clock_for
    from app.config import Settings
    from app.db.connection import write_connection

    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: make demo-time T=2026-10-15T09:00:00+05:30", file=sys.stderr)
        return 2
    settings = Settings()
    clock = clock_for(settings.demo_now, settings.data_dir)
    conn = write_connection(settings.database_path)
    try:
        now = advance(conn, clock, parse_time(args[0]))
    except (NotADemo, ValueError) as e:
        print(f"demo-time: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"demo-time: it is now {now.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
