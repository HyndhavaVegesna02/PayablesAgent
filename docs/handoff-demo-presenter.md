# Handoff: the shrimp-farm demo, and the Demo Presenter page to build

For a fresh Claude Code session, or an engineer, working from a clone of the repository
`github.com/HyndhavaVegesna02/PayablesAgent` (public), branch `main`. It is self-contained: read it, then
[CLAUDE.md](../CLAUDE.md), [docs/demo-shrimp.md](demo-shrimp.md) and
[docs/shrimp-business-context.md](shrimp-business-context.md) (the crop, the actors, the short payment), and
you can start building the Demo Presenter page (part 4).

**Where this material may go.** This repository is public, and the user has accepted that the shrimp
profile, its uploads and its rehearsals are public here. Nothing in this document, the shrimp profile or
the presenter goes to the separate clean public repository (`HyndhavaVegesna02/PayableAgent`) or to the
hackathon submission branch (`DataGrokrAnalytics/hackathon_2026`, `team/team-hs`) without the user's go.
Rule R011 in `.yourteam/rules.md` records this.
Demo day is **Fri 9 Oct 2026**.

## 1. Getting set up from a clone

```
uv sync --all-groups
```

`.env` is not in git. Create it from `.env.example` and fill in:

| Key | Why | How to make it |
| --- | --- | --- |
| `GEMINI_API_KEY` | live Gemini (billed) | a Google AI Studio key on a project with billing headroom |
| `SESSION_SECRET` | the web app refuses to start without it | `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `FERNET_KEY` | mail and uploads are stored encrypted; the worker can't store them without it | `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

Keep `FERNET_KEY` once set: documents stored under one key can't be read under another (reseed if it
changes). Never print or commit `.env`.

**This Windows machine's quirks** (they may not apply to yours):

- Windows Application Control (Device Guard) blocks `make` ("make.exe was blocked by your
  organization's Device Guard policy", exit 4551) and sometimes a fresh venv's `python.exe` / `pytest.exe`. Every `make` target has a plain equivalent, below. If a fresh
  worktree's venv is blocked, run with the main checkout's interpreter:
  `C:\Hyn\PayablesAgent\.venv\Scripts\python.exe -m pytest -q` from the worktree's folder.
- Memory is tight. Claude Code kills background shells when the machine is critically low. Run one heavy
  thing at a time (the full suite takes about 2 minutes; `check_evidence` about 1).
- Run the tests with `DEMO_NOW` and `DEMO_AI` unset (two tests fail if demo values leak in).

Gates the repository expects after any change: `make test` (pytest and import-linter's 9 contracts) and
`make check-evidence`. Without make:

```
uv run python -m pytest -q
uv run python -c "import sys;from importlinter.cli import lint_imports;sys.exit(lint_imports())"
uv run python scripts/check_evidence.py
```

## 2. The product in brief, and the rules that never bend

PayablesAgent is an SME cash-flow and payables agent. It reads bank alerts, statements and bills (email,
PDF, photo, voice note), keeps a deterministic ledger, plans 14 days ahead against the owner's safety
amount, and re-plans as payments clear, bounce or go missing. **It never moves money**: the owner approves
and pays in their own bank app. The full spec is `SME_Cash_Flow_Payables_Agent_TDD_v2.md`.

Invariants (from CLAUDE.md, enforced by tests and import-linter):

- Money is integer paise; no float ever holds an amount.
- Every payable, receivable or transaction state change goes through `app/ledger/writer.py::transition()`.
- `app/planner/` is pure; all code reads time through `app/clock.py`.
- `app/ai/` never imports `ledger`, `db` or `web`. The AI has no tool that approves, pays or sends.
- **The app's route table is fixed** (`tests/test_web_roles.py` asserts it equals the TDD's). That is why
  the presenter must be a separate process (part 4).
- AI-written text is rendered as escaped plain text (no `|safe`), labelled as the assistant's words.

Process: the repository runs on YourTeam (`.claude/skills/yourteam/SKILL.md`, state in `.yourteam/`).
CLAUDE.md asks that every code change go through it: a backlog entry, a lane-appropriate plan, gates, a
batched review. Batches 0 to 23 are recorded in `docs/batches/` and `docs/changes/`.

## 3. The shrimp-farm exercise (done)

### The story

Godavari Aqua Farm, a fictional vannamei shrimp farm in coastal Andhra Pradesh. A crop runs about 110
days on credit (feed and seed from the dealer, the land lease, power for the aerators, the caretaker's
wages) and all the money arrives at the end, through a commission agent who sells the harvest: an advance
on harvest day, then the balance after the processor re-grades, usually short. The demo plays **weeks 15
to 16 of the crop**, the harvest and settlement fortnight, Mon 19 to Mon 26 Oct 2026, on a frozen demo
clock with live Gemini.

| Actor (fictional) | Real-life role | In the app |
| --- | --- | --- |
| Godavari Aqua Farm | the farmer | owner (`owner@example.test` / `owner-demo-pass`) |
| Lakshman | caretaker, monthly wage; sends a Telugu voice note and a slip photo | helper (`helper@example.test` / `helper-demo-pass`): can only add bills |
| Sri Lakshmi Aqua Feeds | feed dealer, season on credit | vendor: ₹25,000 delivery; ₹6,46,800 settlement with a changed bank account |
| Ravi Traders | commission agent selling the harvest | customer: advance ₹2,00,000 (HARVEST-ADV) via the agent's personal UPI "RAVI K"; balance ₹10,15,000 (HARVEST-BAL) paid ₹9,20,000, ₹95,000 short |
| K. Subba Rao | landowner | vendor: lease ₹75,000 due Sat 31 Oct |
| APSPDCL | electricity board | vendor: ₹15,000 |
| Raju Petrol Bunk / Venkat Motors | fuel station / aerator repair shop | vendors: ₹3,000 (voice note), ₹18,000 VM/412 (photo) |
| HDFC Bank | the farm's bank | alerts from `alerts@hdfcbank.example`, account `**7310` |

### The moves

Each move is one clock move; the worker then reads that day's mail with Gemini. The owner's decisions
are made in the app. Exact on-screen text and narration: [docs/demo-shrimp.md](demo-shrimp.md).

| Move | Clock (IST) | What happens | What it proves |
| --- | --- | --- | --- |
| Start | Mon 19 Oct 09:00 | the plan: ₹1,10,000, covered for 14 days | planning, not bookkeeping |
| 1 | Mon 19 Oct 12:00 | dealer's ₹25,000 invoice; the owner confirms | AI reads, code checks, the owner confirms |
| 2 | Tue 20 Oct 10:00 | ₹2,00,000 from "RAVI K"; the exception agent searches the mailbox, finds the weighment slip; its finding is shown; the owner links HARVEST-ADV | the agent loop, traced; the owner decides |
| 3 | Wed 21 Oct 12:00 | ₹6,46,800 settlement with a new bank account: held; the owner rejects the details; the plan shows the shortfall; the owner asks Ravi Traders to pay early | fraud held by code; shortfall options computed |
| 4 | Thu 22 Oct 10:00 | the helper uploads a Telugu voice note (Raju diesel ₹3,000, due 24 Oct) and a slip photo (Venkat Motors ₹18,000, due 25 Oct); the owner confirms both and approves Thursday's 4 payments (₹51,000) | real-world inputs; the helper's role; owner approval |
| 5 | Fri 23 Oct 16:00 | ₹9,20,000 from RAVI TRADERS, short; the agent finds the payment advice; the owner links HARVEST-BAL "short by ₹95,000"; the floor is restored (lowest ₹4,32,200) | partial and short payments recorded honestly |
| 6 | Mon 26 Oct 11:00 | the dealer's NEFT matches the approved bill: PAID | the loop closes |

### What was built for it (batches 21 to 23)

| Change | What | Where |
| --- | --- | --- |
| CHG-057 | `explain_credit`: the owner says which invoice a bank credit paid, with the agent's finding shown (labelled, nothing pre-selected); the owner role may confirm a receivable; a short or over payment is recorded in the event, the invoice amount never edited | `app/ledger/reconcile.py`, `app/web/actions.py`, `app/web/routes/attention.py`, `app/web/templates/attention.html`, `app/domain/states.py`, migration `0006_explain_credit.sql`, `tests/test_owner_explains_credit.py` |
| CHG-058 | the shrimp profile: alternative config (`APP_CONFIG_PATH`), canned-reply store (`FIXTURE_REPLIES_PATH`), env launcher, seed, inbox, demo script, rehearsal driver | `config.shrimp.yaml`, `.env.shrimp`, `.env.shrimp-fixtures`, `scripts/with_env.py`, `fixtures/shrimp_seed.py`, `fixtures/shrimp_inbox/`, `fixtures/shrimp_ai_replies.json`, `scripts/rehearse_shrimp.py`, `docs/demo-shrimp.md`, `tests/test_shrimp_profile.py` |
| CHG-060 | move 4 as two bills (voice and photo), Thursday's payments approved at move 4 | the same files |
| CHG-061 | the driver finds bills by content, handles a misread buyer's record (owner rejects it), clearer wording in inbox 02 and 06, canned replies for the real uploads | the same files |

Deferred minors are in CHG-059 (`docs/changes/`).

### Running it

`.env.shrimp` holds no secrets; it is applied as process environment on top of `.env`, for these
commands only (its own database `./data/shrimp.db`, files `./data/shrimp-files`, traces
`./traces/shrimp`, demo clock starting Mon 19 Oct 09:00, no SMTP).

| What | With make | Without make |
| --- | --- | --- |
| reseed (do first; refuses any database but `data/shrimp.db`) | `make reseed-shrimp` | `uv run python scripts/with_env.py .env.shrimp DATABASE_PATH=./data/shrimp.db -- python -m fixtures.shrimp_seed --fresh` |
| web app, http://localhost:8000 (keeps running) | `make run-shrimp` | `uv run python scripts/with_env.py .env.shrimp -- python -m uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000` |
| worker, live Gemini (keeps running) | `make worker-shrimp` | `uv run python scripts/with_env.py .env.shrimp -- python -m app.worker` |
| worker on canned replies (no Gemini) | `make worker-shrimp FALLBACK=1` | `uv run python scripts/with_env.py .env.shrimp .env.shrimp-fixtures -- python -m app.worker` |
| move the clock | `make demo-time-shrimp T=2026-10-20T10:00:00+05:30` | `uv run python scripts/with_env.py .env.shrimp -- python -m app.demo 2026-10-20T10:00:00+05:30` |
| rehearsal, offline (free) | `make rehearse-shrimp` | `uv run python scripts/rehearse_shrimp.py --ai fixtures` |
| rehearsal, live (billed; only when authorised) | `make rehearse-shrimp ARGS="--ai live --yes-spend --max-usd 1.00"` | `uv run python scripts/rehearse_shrimp.py --ai live --yes-spend --max-usd 1.00` |

Reset between run-throughs: stop the app and worker, delete `./data/shrimp-files` and `./traces/shrimp`,
reseed.

### The real uploads

`fixtures/shrimp_uploads/voice-diesel-raju.mp3` (a real Telugu recording, amount and date said in English
because code reads no Telugu number words) and `fixtures/shrimp_uploads/repair-slip-venkat.jpg` (a phone
photo of the slip, with the VENKAT MOTORS header) are committed. Their canned replies in
`fixtures/shrimp_ai_replies.json` are keyed by file name, and at load `app/ai/fixture_backend.py` matches
an upload by the sha256 of that named file's bytes. They are what live rehearsal 1 read, so offline runs
and `FALLBACK=1` replay them on any clone. The `PLACEHOLDER-*` files stay for the tests.

### Live rehearsals (reference data for the presenter's activity feed)

| Run | Result | Report |
| --- | --- | --- |
| First, Wed 7 Oct 23:55 | the start and moves 1 and 2 pass; moves 3 to 6 don't | [docs/shrimp-rehearsals/2026-10-07T235555-live](shrimp-rehearsals/2026-10-07T235555-live/report.md) |
| Second, Thu 8 Oct 02:59 | every move passes | [docs/shrimp-rehearsals/2026-10-08T025927-live](shrimp-rehearsals/2026-10-08T025927-live/report.md) |

Each report gives its calls and cost. Each folder holds `report.md`, `report.json` and `traces/` (one
JSONL file per worker job attempt, by demo date). The first rehearsal went wrong because live Gemini
sorted the buyer's weighment slip (inbox 02) as a ₹12,15,000 bill and the driver then took the wrong
bill; CHG-061 fixed the driver and reworded 02 and 06. The second sorted both correctly. Known live variation: the agent's step count (3 to 6), the slip
vendor's spelling ("VENKAT MOTORS/…" or "VENKAT MOTORS / …"), and whether the agent's summary lists the
deductions. On stage, if the slip appears as a bill, the owner rejects it.

## 4. To build: the Demo Presenter page

### Why

Today the demo needs three terminals (app, worker, clock commands) and the agent's work is only visible
in a terminal log. The presenter replaces the terminals with one page: the presenter tells the story,
presses **Next** for each move, and the panel watches Gemini and the agent work live. **Every owner
decision still happens in the real app**: confirming bills, linking credits, rejecting the bank change,
approving payments, and the helper's uploads on Thursday. That is the product's point; the presenter
never clicks them.

### What the user wants

- One command starts everything: the shrimp app, the worker and the presenter page.
- A card per move: the day and time, what just arrived, what to say, what to do in the app (from
  [docs/demo-shrimp.md](demo-shrimp.md)).
- **Next** moves the demo clock to the next move. It stays disabled while the worker is still processing,
  so the presenter can't click ahead of Gemini.
- A live activity feed: Gemini sorting and reading each email or upload, and the exception agent's steps
  (tool, arguments, what it found), with model, thinking level, latency, tokens and cost.
- A fallback switch: restart the worker on canned replies if Google refuses calls (429, spending cap).
- A reset button.

### Architecture (proposed; adjust with reasons)

- **A separate process on its own port** (e.g. `:8001`), its own small FastAPI or plain server, in a new
  top-level package (e.g. `presenter/`) or under `scripts/`. **Never add routes to `app/`** (the route
  table is fixed by tests), and `app/` must never import the presenter.
- **Launcher.** It starts the app and the worker as child processes with the shrimp environment, the same
  way `scripts/with_env.py` does, and stops them cleanly. Fallback = restart the worker with
  `.env.shrimp-fixtures` added. Reset = stop both, delete `./data/shrimp-files` and `./traces/shrimp`,
  reseed, start both. Windows: use `subprocess.Popen` with a new process group and terminate the whole
  tree; `make` may be blocked, so call Python directly.
- **Next** calls `app.demo.advance(conn, clock, to)` (what `make demo-time-shrimp` runs): forward only;
  it queues a mail poll and, past a Monday 07:00, the Monday plan. The app also has an owner-only demo
  route, `POST /demo/time`, used by the Settings page's "Move the clock" form; calling the module directly
  avoids a login and CSRF from the presenter.
- **Worker idle** (to enable Next): in the `job` table (`app/db/schema.sql`: `status` in queued, running,
  done, failed, dead; `run_after` in demo time), no job is `queued` with `run_after` at or before the demo
  now and none is `running`, and the worker's heartbeat file `data_dir/worker.heartbeat`
  (`app/worker.py`) is fresh. Read the database through `app/db/read.py::read_only_connection` (as
  `app/main.py` does).
- **Activity feed.** Tail the trace files under `TRACE_DIR` (`./traces/shrimp/<demo date>/job-<n>-attempt-<k>.jsonl`)
  by `wall_time`. Each line is one step with `run_id`, `step`, `timestamp` (demo time), `wall_time`,
  `tool`, `arguments`, `result`, and on model calls also `model`, `thinking`, `validation`,
  `latency_ms`, `retries`, `escalation_rule`, `tokens`, `cost_micro_usd`. `app/trace/tracer.py` writes
  them; `app/trace/view.py` renders a run in the terminal and is the reference for wording. Push updates
  with server-sent events or HTMX polling (the app already vendors HTMX; no CDN, no build step).
- **Show the AI's text as escaped plain text**, labelled as the assistant's, as the app does. Never show
  secrets, and never render the API key or `.env` values.
- **Layout.** The app in one browser window and the presenter in another, side by side, is the safe
  default. Embedding the app in an iframe should work (the app sets no frame-blocking header and its
  cookies are SameSite=Lax on the same host) but test it.
- **The moves list** (times, titles, say, do, expected end state) can be lifted from
  `scripts/rehearse_shrimp.py` and `docs/demo-shrimp.md`; keep one source of truth if you can.

### Constraints

- Don't change `fixtures/seed.py`, `fixtures/test_inbox/`, `fixtures/ai_replies.json`, `evals/`,
  `docs/evals/`, `docs/traces/`, `config.yaml` or any prompt file: committed evidence depends on them
  (`make check-evidence` regenerates and diffs it).
- No changes to the app's behaviour are needed. If one seems needed, propose it as its own change.
- `make test`, the 9 import-linter contracts and `make check-evidence` stay green.
- No live Gemini while building: develop and test the presenter against `FALLBACK=1` (canned replies). A
  live run costs well under the `--max-usd 1.00` cap (each rehearsal report gives its cost) and needs the
  user's go.

### Acceptance

1. One command starts the app, the worker and the presenter; Ctrl+C or a Stop button ends all three.
2. Next walks Start and moves 1 to 6, disabled while the worker is busy; each card shows the right day,
   narration and what to do in the app.
3. The feed shows each Gemini call and agent step within a few seconds, with model, thinking, tokens,
   latency and cost, and the running total for the fortnight.
4. The owner's actions in the app, done by hand between Nexts, take the fortnight to the same end states
   the rehearsal driver checks (lowest ₹4,32,200 after move 5; the dealer's bill PAID after move 6).
5. The fallback switch restarts the worker on canned replies and the feed says so; Reset returns to Mon 19
   Oct 09:00 with a fresh database.
6. A test plays the presenter's Next sequence in fixture mode, without a browser.
7. Works on Windows without `make`.

### Open choices for the builder

- A new `presenter/` package, or a single presenter script under `scripts/`; the framework (FastAPI plus
  Jinja and HTMX matches the app).
- Server-sent events or polling for the feed.
- Showing cost in µUSD, USD or ₹.
- Whether Next also opens the right app page (This week or Needs attention).

## 5. Repository state at handoff

- This repository (`origin`, public by the user's choice): `main` holds everything above, including this
  document.
- Public repository `HyndhavaVegesna02/PayableAgent`, `main` = `1a45449`: the reviewed product without
  the shrimp profile. Don't push shrimp material there.
- Hackathon submission `DataGrokrAnalytics/hackathon_2026`, branch `team/team-hs` = `5decddb`: filtered
  real history plus the public tree. Its rules: no force-push, no other branches, no history rewriting.
  Any later update must be a fast-forward on top of `5decddb`, and nothing shrimp goes there without the
  user's go.
