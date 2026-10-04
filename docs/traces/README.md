# Traces

Four traces of eval scenario 7, *Missed alert causes drift*
(`evals/scenarios/07-missed-alert-causes-drift/`): the bank alert for a ₹20,000 debit never reached the
ledger, so on Thu 15 Oct the 23:00 recheck finds the bank's balance ₹20,000 below the calculated one and
opens a drift case. Can the exception agent find what's missing?

| File | Run | What it shows |
| --- | --- | --- |
| [`live-failure.jsonl`](live-failure.jsonl) | **Official failure.** Gemini, the live pilot (`docs/evals/2026-10-04-live-pilot/`), job 11 | The agent finds the missed alert but proposes it with field names of its own; code refuses the candidate, and then accepted a final answer that relied on nothing. The gap stayed open. |
| [`live-success.jsonl`](live-success.jsonl) | **Official success.** Gemini, the AFTER (`docs/evals/2026-10-04-live-after-batch-8/`), job 11 | Once batch 8 named the fields and refused an empty resolution: two searches, one VALID candidate, and code writes the transaction. |
| [`success.jsonl`](success.jsonl) | Fixture AI, `config.yaml` | The scripted run of the whole scenario, every job; deterministic, so a test regenerates it. |
| [`failure.jsonl`](failure.jsonl) | Fixture AI, `evals/variants/regress-max-steps.yaml` | The same, with the agent's step cap cut to 2: code's escalation takes over. |

The live traces are copies of the job-11 files in those reports' `traces/` folders, which a test checks
byte for byte. They predate CHG-047, so their lines have no `wall_time`, `latency_ms` or `attempt`; traces
written since have them.

## live-failure.jsonl, line by line

The job is `run_case` for the drift case, at 23:00 on Thu 15 Oct (business time).

- **Line 1:** code's opening rule starts the agent at `medium` thinking.
- **Lines 2–3:** the agent reads the case file (the gap, the account, the dates) and searches the mailbox
  for "4821 20000". Nothing matches.
- **Lines 4–5:** it asks for the ledger with the account as `XXXX4821`. Code refuses the call: the tool takes
  the last four digits (`refused: ('account',): String should match pattern '^[0-9]{4}$'`). A refused call is
  a step the agent reads, not a crash.
- **Lines 6–7:** it retries with `4821` and reads the one recorded debit (the ₹35,000 electricity bill).
- **Lines 8–9:** it searches for "4821" and finds the alerts, the missed ₹20,000 one among them.
- **Line 10:** the agent names the missed alert. Look at `tokens.thoughts` here against the other calls: this
  is the step where it worked hardest.
- **Line 11 (the failure):** `add_candidate` with field names of its own (`account`, `amount`...). Code's
  rule checks refuse it: `candidate 2: INVALID (schema: 9 field error(s): Field required)`. The tool's
  refusal did not say which fields it wanted.
- **Lines 12–13 (the second failure):** the agent answers anyway, and `apply_final` records `evidence
  checked` with `nothing to write`. The answer cited the message but relied on no VALID candidate, so the
  gap stayed open. That's the hole batch 8 closed (CHG-031): a drift resolution must rely on a VALID
  candidate, and every refusal names the fields.

## live-success.jsonl, line by line

The same job, with batch 8's fixes in.

- **Line 1:** starts at `medium`.
- **Lines 2–3:** a Gmail-style search, `from:alerts@hdfcbank.example 4821`. On this build's folder mail source
  it found nothing (the trace showed it; the folder source has understood `from:` since).
- **Lines 4–5:** a plain search for "4821" finds the alerts.
- **Lines 6–7:** the agent proposes the missed alert with the named fields (`account_last4`, `amount_text`...),
  and code's rule checks pass it: `candidate 2: VALID, every rule check passed`.
- **Lines 8–9:** the final answer relies on candidate 2. `apply_final` checks the evidence (the cited
  message came from this case's own search; the candidate is VALID) and code, not the model, writes it:
  `candidate 2: bank_txn 2 written`. The drift check then finds no gap.

The fixture traces below tell the same story from every job's side.

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
- `timestamp` is business time (the clock a demo or an eval moves); `wall_time` is when the step really ran.
  An AI call also has `latency_ms`, `attempt` (the job's attempt number) and `retries` (the retries made for
  that call: an eval guard's 429 backoffs; 0 in the product, whose SDK retries are off).

The trace never holds an API key, a password or a file's bytes. Files are
recorded by type, size and sha256, and any field whose name ends in
`password`, `token`, `key` or `secret` is redacted.

## The fixture traces

`scripts/make_traces.py` writes `success.jsonl` and `failure.jsonl` on the fixture AI, and
`tests/test_evidence_docs.py` regenerates them at every commit and fails if they differ. On the fixture AI the
token counts and costs are zero, and the `model` field names the configured model, not one that was called.
The two wall-clock fields are left out of them, since they differ on every run.

### success.jsonl, line by line

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

### failure.jsonl: the same run with the step cap at 2

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
