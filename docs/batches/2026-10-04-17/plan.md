# Batch 17: plan (the judge's findings, offline; then a live ablation v2)

**Branch:** `batch-17`, cut from main at fa88b80. Seven changes, offline; no live spend in this batch. The
live ablation v2 runs after the PO's verdict and the merge, from main at one commit, and only once the user
confirms it in this terminal. One review round for the batch.

| Change | Lane | Why that lane |
|---|---|---|
| CHG-046 docs | direct | prose only, figures from committed reports (D25) |
| CHG-047 traces | planned | the tracer is used by every job; its fields are read by metrics, the trace view and the curated traces |
| CHG-048 ablation table | direct | one module, one command |
| CHG-049 new knock-outs | planned | three new seams into the agent loop, the final-answer check and the tool registry |
| CHG-050 path budgets | direct | scenario files only |
| CHG-051 harder variants | planned | new fixtures and scripted replies in the one store |
| CHG-052 reusable harness | direct | README only |

**CHG-047.** The tracer stamps every step with wall-clock time (`wall_time`) beside the business clock's
`timestamp`. An AI call records `latency_ms`, and `attempt` (the job's attempt number, which the worker sets
on its tracer). Its `retries` are the retries the backend made for that call (the eval guard's 429 backoffs;
0 in the product, whose SDK retries are off), not a hard-coded 0. The reply preview grows from 200 to 2,000
characters. The bare harness keeps its traces next to its run. The live pilot's job-11 trace becomes the
official failure trace and a live AFTER trace (07 resolved) the official success trace, each with a "how to
read it" walkthrough; the fixture pair stays as the second pair.

**CHG-049.** Seams, like the existing four:
- `no_case_file`: `app.agent.loop.next_step` is given the run's growing history (every earlier context and
  reply, appended) instead of the case file;
- `no_evidence_gate`: `app.jobs.run_case.apply_final` accepts a RESOLVED answer without the citation and
  candidate checks;
- `all_tools`: `app.agent.tools.TOOLS` also offers write-capable tools (mark a bill paid, set a balance) that
  act on the run's own database copy.
Each has an outcome check that fails when the control is gone, proved in fixture mode with scripted replies
kept in fixtures/ai_replies.json.

**CHG-050.** Every agent scenario (02, 07, 08, 10) gains trajectory checks that apply live too: the agent's
steps at most its budget, and refused calls at most a small number.

**CHG-051.** Three new scenarios, fixture-only and marked "not yet run live": a hidden instruction in an
attachment's name and body, a debit whose amount matches bills of two vendors, and a statement row with noise
in its description.

**CHG-048.** `python -m evals.report ablation-combine` builds one table from ablation report.json files:
harness by scenario, success with spread, full-vs-bare delta, each knock-out's drop, and the component that
earned the most. The README discusses the null results.

**CHG-046, CHG-052.** Docs; CHG-046 last, so it can cite the new files.
