# Two curated traces

Both traces are one run of eval scenario 7, *Missed alert causes drift*
(`evals/scenarios/07-missed-alert-causes-drift/`), on the fixture AI.
`scripts/make_traces.py` writes them, and `tests/test_evidence_docs.py`
regenerates them at every commit and fails if they differ, so the files are
always what the code writes today. The test also pins the control-point lines
this walkthrough leans on (19, 32 and 45 in the success trace; 18, 19, 20 and
36 in the failure trace). On the fixture AI the token counts and costs are zero,
and the `model` field names the configured model, not one that was called; a
live run writes the same fields with real values.

| File | Config | What it shows |
| --- | --- | --- |
| [`success.jsonl`](success.jsonl) | `config.yaml` as committed | A gap the code can't explain, recovered from the mailbox by the agent and written to the ledger by code. |
| [`failure.jsonl`](failure.jsonl) | `evals/variants/regress-max-steps.yaml` (the agent's step cap cut to 2) | The same story when the agent runs out of steps, and code's escalation rules take over. |

## How to read a trace line

Each line is one step, written as it happened (`app/trace/tracer.py`). The
fields to look at:

- `run_id` is the job and its attempt (`job-11-attempt-1`). `step` counts
  within that job.
- `tool` says what kind of step it is:
  - `ai.call:<job>` is one model call (`sort`, `extract:bank_alert`,
    `exception` for the agent, `explain`);
  - `agent:<tool>` is one of the agent's five tools, run by code;
  - `validate`, `route`, `reconcile` and `apply_final` are code deciding;
  - `escalation` is code's escalation rule (`app/agent/escalation.py`).
- `result` is what came back: for a model call, the start of its reply.
- `validation` is the schema check on a model reply, or the rule checks on a
  record.
- `escalation_rule` names the rule that fired, if one did.
- `thinking`, `tokens` and `cost_micro_usd` are the model's level and what the
  call cost.

The trace never holds an API key, a password or a file's bytes. Files are
recorded by type, size and sha256, and any field whose name ends in
`password`, `token`, `key` or `secret` is redacted.

## success.jsonl, line by line

**Lines 1–8: the gap appears.**
- On Thu 15 Oct at 09:00 the mail check finds nothing new (line 1).
- At 13:00 it stores one email (line 2): a ₹35,000 debit alert from HDFC.
- The model sorts it as a bank alert (line 3, `low` thinking) and reads its
  fields (line 4, `medium`). Code checks them (line 5) and writes the
  transaction (line 6).
- No bill matches the debit (line 7). The alert's available balance is
  ₹20,000 below the balance the ledger calculates, so the reconciler books a
  recheck for 23:00 rather than raising the alarm on one alert (line 8).

**Lines 9–11: the unexplained debit goes to the owner.** The ₹35,000 debit
opens an `unknown_txn` case (agent_case 1). The fixture AI has no script for
it, so the agent answers NEEDS_OWNER at once (line 10), and an owner alert is
queued. With no SMTP host configured, the alert waits unsent and nothing fails
(line 11).

**Lines 12–19: the agent recovers the missed alert.**
- At 23:00 the gap is still there. The account becomes CHECKING and drift
  case 2 opens (line 12).
- The case starts at `medium` thinking, because its stake is under the
  escalation amount (line 13).
- The model asks to search the mailbox (line 14). The search finds
  `11-debit-shree-transport-missed.eml` (line 15): a ₹20,000 debit alert dated
  Tue 13 Oct. The mail check never read it, because it was dated before the
  check's window.
- The model proposes it as a record (line 16). Code runs every rule check on
  that candidate: VALID (line 17).
- The model answers RESOLVED, citing that email (line 18).
- **Line 19 is the control point.** `apply_final` checks the evidence: the
  cited message came from this case's own search, and the candidate it relied
  on is VALID. Only then does code write `bank_txn 2`. The model never wrote
  anything.

**Lines 20–24: the books catch up.**
- The plan's summary falls back to its template, because the fixture AI has no
  canned summary (lines 20–22).
- The recovered debit matches no bill (line 23).
- The balances now agree (line 24): the gap is closed and the account is OK
  again.

**Lines 25–45: escalation, working as designed, on a second case.** The
recovered ₹20,000 debit to SHREE TRANSPORT matches no bill either, so it opens
its own `unknown_txn` case (agent_case 3), which runs the fixture's escalation
script:
- At `medium`, two proposed records fail their checks (lines 29 and 31). Rule
  `max_validation_failures` ends the run, and code reruns the case at `high`
  (line 32).
- The high run searches without finding anything until rule `max_steps` ends
  it (line 45). The case goes to the owner as a question.

**Lines 46–47:** the owner alert waits for SMTP, and the plan's summary has
nothing new to say.

## failure.jsonl: the same run with the step cap at 2

Lines 1–17 are the same as in success.jsonl. Then:

- **Line 18:** the drift case has used its two steps (a search and a proposal)
  before it could answer. Rule `max_steps` ends the medium run, and code reruns
  the case at `high`.
- **Lines 19–20:** at `high` the model answers RESOLVED at once, and
  `apply_final` writes the transaction, as before.
- **Lines 31 and 36:** the second case hits the cap at medium after a search
  and one failed proposal (line 31). It hits it again at high after two searches (line 36),
  and goes to the owner.

The end result is the same: the missed debit is in the ledger and the gap is
closed. The path is worse: the drift case needed a second run at high thinking
to finish work that medium thinking does in one. The eval suite scores the
path as well as the result: scenario 7's trajectory check
`drift-resolved-in-its-first-run` fails here, in the report's Path column, while
the end result still counts as a success. That makes this config the regression the suite catches
([docs/evals/README.md](../evals/README.md)).
