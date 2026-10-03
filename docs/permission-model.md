# Permission model

Who can do what in PayablesAgent, and where the code enforces it. The two
tables marked *generated* come from the code itself (`scripts/make_docs.py`),
and `tests/test_evidence_docs.py` fails if they differ from it.

## The four actors

- **The owner** logs in to the web app, approves the plan, and pays through
  their own bank app. Only the owner confirms what the system has read,
  answers its questions, and accepts a vendor's new bank details.
- **The helper** logs in too, and can only add things: upload a bill, a photo,
  a statement or a voice note, or type an entry.
- **The AI** is Gemini, called by the worker. It sorts and reads documents,
  explains a plan, and runs exception cases as the agent. Everything it says
  is checked by code before anything is stored, and it can only propose.
- **Code** is the worker and the web app's actions. It writes the ledger,
  through `app/ledger/writer.py::transition()` only, and only when the owner
  asked or a rule check passed.

Nobody moves money. The app has no connection to any bank.

## What each actor may do

| Action | Owner | Helper | AI | Code |
| --- | --- | --- | --- | --- |
| Approve the payments for a payment day | yes (web) | no | no tool for it | no; it records the owner's approval |
| Mark a bill paid | yes (web) | no | no tool for it | when a bank debit matches the approved payment (the reconciler) |
| Confirm a record read from a document | yes (web) | no | proposes it (a candidate) | applies the owner's confirmation |
| Add a document or an entry | yes | yes | no | stores it, and queues it to be read |
| Accept a vendor's new bank details | yes (web) | no | no tool for it | flags the change and asks the owner |
| Choose a shortfall option | yes (web) | no | no | applies the choice and replans |
| Change the safety amount and other settings | yes (web) | no | no | no |
| Answer the agent's question | yes (web) | no | asks it (one question, plain text) | applies the answer |
| Write the ledger | no (only through an action) | no | refused: the writer rejects every `agent:*` actor | yes, through `transition()` only |
| Email the owner | no | no | cannot reach it: `app.ai` and `app.agent` never import `app.notify` | yes: fixed templates, recipient from the database |

## The exception agent's tools (generated)

<!-- generated: python -m app.agent.permissions -->
| Tool | Arguments | May | Summary |
| --- | --- | --- | --- |
| `search_gmail` | query, limit | reads; writes nothing; reads this business's mailbox | Searches this business's mailbox; remembers the message IDs it returns. |
| `get_ledger` | table, account, date_from, date_to, amount_text, party | reads; writes nothing | Reads ledger rows on a read-only connection; at most 50. |
| `run_planner` | drop_payable_ids, receivable_dates | reads; writes nothing | A what-if plan; writes nothing. |
| `add_candidate` | record_type, message_id, fields | writes a candidate row (and the message it came from); never the ledger | Proposes a record from a message this case found; rule-checked; never the ledger. |
| `ask_owner` | question, choices | writes one owner question; ends the run until the owner answers | One plain-text question (at most 300 characters, 4 choices); ends the run. |
<!-- end generated -->

A tool name that isn't in this table is refused and noted in the case file.
So are arguments its model doesn't allow (every args model forbids extra
keys), and the same call twice in a row. A refusal still counts as a step.
[docs/notes/agent-permissions.md](notes/agent-permissions.md) covers what code
does with the agent's final answer.

## Who may call each web route (generated)

Every route that needs a login names its roles with `require(...)`. The check
runs on the server, and every POST also needs the session's CSRF token.
`tests/test_web_roles.py` checks this list against the TDD's route table, and
checks that a helper gets 403 on every owner-only route.

<!-- generated: scripts/make_docs.py routes -->
| Method | Route | Who may call it |
| --- | --- | --- |
| GET | `/` | owner |
| GET | `/accounts` | owner |
| POST | `/accounts/{account_id}/confirm-balance` | owner |
| GET | `/add` | owner, helper |
| GET | `/api/health` | anyone (no login) |
| GET | `/api/plan/current` | owner |
| POST | `/api/what-if` | owner |
| GET | `/attention` | owner |
| POST | `/candidates/{candidate_id}/confirm` | owner |
| POST | `/candidates/{candidate_id}/reject` | owner |
| POST | `/demo/time` | owner (demo mode only: registered when DEMO_NOW is set) |
| POST | `/documents/{document_id}/unlock` | owner |
| POST | `/entries` | owner, helper |
| GET | `/login` | anyone (no login) |
| POST | `/login` | anyone (no login) |
| POST | `/logout` | anyone (no login) |
| POST | `/options/{option_id}/choose` | owner |
| POST | `/parties/{party_id}/bank-change` | owner |
| POST | `/payables/{payable_id}/mark-paid` | owner |
| POST | `/plans/{run_id}/approve` | owner |
| POST | `/questions/{question_id}/answer` | owner |
| GET | `/settings` | owner |
| POST | `/settings` | owner |
| POST | `/uploads` | owner, helper |
<!-- end generated routes -->

## Where each line is enforced

| Rule | Enforced by | Tested by |
| --- | --- | --- |
| Only the writer writes ledger tables | an AST/regex scan of `app`, `fixtures` and `evals`; one exemption, evals/bare.py, the ablation's harness without a writer, on its own scratch database | `tests/test_ledger_write_guard.py` |
| The writer refuses `agent:*` actors | `app/ledger/writer.py`, before any SQL | `tests/test_ledger_writer.py` |
| The agent can't import the writer, the web app or the pipeline | import-linter contract | `make test` (lint-imports) |
| The AI and the agent never reach owner email | import-linter contract | `make test` (lint-imports) |
| The agent's SQL writes only `candidate`, `owner_question`, `agent_case`, `source_document` | an AST scan of `app/agent` | `tests/test_agent_boundary.py` |
| Approving a stale plan is refused (409) | `app/web/actions.py::approve` | `tests/test_web_week.py` |
| A RESOLVED answer needs evidence | `app/jobs/run_case.py::apply_final` | `tests/test_run_case_job.py` |
| A helper gets 403 on owner routes | `app/web/auth.py::require` | `tests/test_web_roles.py` |
