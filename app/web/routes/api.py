"""GET /api/plan/current and POST /api/what-if (owner only; TDD Part 2,
"HTTP routes"). JSON for evals and debugging. What-if writes nothing."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.web import actions, repo
from app.web.auth import User, db, owner_only

router = APIRouter()


@router.get("/api/plan/current")
def plan_current(user: User = Depends(owner_only), conn: sqlite3.Connection = Depends(db)):
    view = repo.plan_view(conn, user.business_id)
    if view is None:
        return JSONResponse({"plan": None})
    run = view.run
    return JSONResponse({
        "plan": {
            "run_id": run["id"], "created_at": run["created_at"], "triggered_by": run["triggered_by"],
            "inputs_sha256": run["inputs_sha256"], "planner_version": run["planner_version"],
            "opening_cash_paise": run["opening_cash_paise"], "lowest_balance_paise": run["lowest_balance_paise"],
            "lowest_on": run["lowest_on"], "valid": bool(run["valid"]), "safety_paise": view.safety_paise,
            "lines": [
                {"payable_id": ln.payable_id, "name": ln.name, "decision": ln.decision,
                 "pay_on": ln.pay_on and ln.pay_on.isoformat(), "amount_paise": ln.amount_paise,
                 "reason": ln.reason, "status": ln.status}
                for ln in sorted(view.lines, key=lambda ln: ln.payable_id)
            ],
            "days": [{"day": d.day.isoformat(), "balance_paise": d.balance_paise} for d in view.days],
            "options": [
                {"id": o.id, "kind": o.kind, "label": o.label, "params": o.params,
                 "lowest_balance_paise": o.lowest_balance_paise, "meets_rule": o.meets_rule, "chosen": o.chosen}
                for o in view.options
            ],
        }
    })


@router.post("/api/what-if")
async def what_if(request: Request, user: User = Depends(owner_only), conn: sqlite3.Connection = Depends(db)):
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise actions.Refused("Send a JSON object.") from None
    return JSONResponse(actions.what_if(conn, user, body, clock=request.app.state.clock))
