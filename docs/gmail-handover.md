# Gmail handover

Everything around Gmail is built and tested against a folder of `.eml` files. What is left is the Gmail side
itself: a `GmailSource`, the OAuth flow and three routes. This page says what exists, what to build, and how
to test it without touching a real mailbox. The spec is TDD Part 2, "Gmail ingestion" (and the routes table
just above it); the backlog entry is `docs/changes/CHG-009-live-connections.md`.

## 1. What exists

| Piece | Where | What it does |
|---|---|---|
| `MailSource` protocol | `app/ingest/mail_source.py` | `list_new(since, senders)`, `fetch(ref)` (RFC 2822 bytes + attachments), `search(query, limit=20)`. Also `MessageRef`, `RawMessage`, `MessageSummary`, `Attachment`. |
| `EmlFolderSource` | `app/ingest/eml_folder.py` | The reference implementation. Reads `TEST_INBOX_PATH`, releases each file by its Date header against the injected `Clock`. `search` understands Gmail's `from:`, `subject:`, `after:` and `before:` (YYYY/MM/DD or YYYY-MM-DD); every other word must appear in sender, subject or body. |
| Source selection | `app/ingest/pipeline.py::mail_source(settings, clock)` | Returns `EmlFolderSource` for `MAIL_SOURCE=eml_folder`; for `gmail` it raises `PermanentJobError` today. This is the one switch to change. `app/jobs/run_case.py` uses the same function for the agent. |
| `poll_mail` job | `app/ingest/pipeline.py::handle_poll_mail` | Senders = every account's `alert_senders` plus `config.yaml` `mail.vendor_senders`. `since` = last sync minus one day (`_since`; first sync: the opening-balance date). Stores each message encrypted as a `source_document`, queues one `process_document` per document, then writes `sync_state`. Scheduled every `mail.poll_minutes` (5) by `app/worker.py`. |
| Dedupe | `source_document` | `UNIQUE (business_id, kind, external_ref)`. `external_ref` is the Message-ID header (or `sha256:<hash>` without one); a message is also skipped if its content hash is already stored. |
| `gmail_connection` table | `app/db/migrations/0001_init.sql` | One row (`id = 1`). `scope` has a CHECK: only `https://www.googleapis.com/auth/gmail.readonly`. `refresh_token_enc` (Fernet; NULL after disconnect), `status` CONNECTED or DISCONNECTED, `connected_at`, `disconnected_at`, `last_error`. Access tokens are never stored. |
| `sync_state` table | same | `source` ('gmail' or 'eml_folder'), `last_synced_at`. |
| `reconnect_gmail` question | `owner_question.kind` CHECK | The kind exists; nothing opens it yet, and `app/web/templates/attention.html` has no branch for it. |
| `GMAIL_CONNECTED`, `GMAIL_DISCONNECTED` | TDD event names | Not written anywhere yet. `event.event_type` is free text; the ledger writer has no public helper for a non-ledger event, so add one in `app/ledger/writer.py` beside `update_business_settings`. |
| Accounts placeholder | `app/web/templates/accounts.html` | Shows "Not connected (set up later)" under **Gmail**. |
| `search_gmail` tool | `app/agent/tools.py::search_gmail` | Calls `ctx.mail.search(query, limit)` on whatever `MailSource` the job built, remembers every message ID it returns (only those may be cited), and returns one line per message. The prompt (`app/ai/prompts/exception_agent.v1.md`) tells the agent the operators above. |
| Settings | `app/config.py` | `google_client_id`, `google_client_secret`, `google_redirect_uri`, `fernet_key`, `mail_source`. |
| Dependencies | `pyproject.toml` | `google-api-python-client`, `google-auth`, `google-auth-oauthlib` and `httpx` are already pinned. |

## 2. What to build

1. **A new `gmail.py` in `app/ingest/`, with `class GmailSource`** implementing `MailSource`:
   - `__init__(conn_row, fernet_key, client_id, client_secret, clock)`: build `google.oauth2.credentials.Credentials`
     from the decrypted refresh token; google-auth refreshes the access token in memory only.
   - `list_new`: `users.messages.list` with `q = "from:(a@x OR b@y) after:YYYY/MM/DD"`, paging through
     `nextPageToken`.
   - `fetch`: `users.messages.get(format="raw")`, base64url-decode to bytes; attachments come from parsing the
     bytes the same way `eml_folder.attachments()` does.
   - `search`: `messages.list(q=query, maxResults=limit)` and `messages.get(format="metadata")` for sender,
     subject, date and snippet.
   - `MessageRef.id` is the Gmail message ID (what `fetch` takes, and what `search` returns to the agent).
     Dedupe needs nothing special: `poll_mail` and the agent's `add_candidate` (`app/agent/tools.py::_document_for`)
     both key `external_ref` on the Message-ID header inside the raw bytes, so a message reached either way
     is stored once.
2. **A new `gmail_oauth.py` in `app/ingest/`**: `connect_url(state)` (scope `gmail.readonly`, `access_type=offline`,
   `prompt=consent`), `callback(code)` (exchange, then **refuse** if the granted scope is anything else),
   `revoke(token)`.
3. **Three routes** (owner only; put them in a new `gmail.py` in `app/web/routes/` and add it to the module list
   that `app/web/app.py` passes to `include_router`):
   - `GET /gmail/connect` stores a random `state` in the session and redirects.
   - `GET /gmail/callback` checks `state`, runs `callback`, Fernet-encrypts the refresh token into
     `gmail_connection` (status CONNECTED), writes `GMAIL_CONNECTED`, and queues `poll_mail`
     (`queue.enqueue_poll_mail`).
   - `POST /gmail/disconnect` revokes with Google, sets `refresh_token_enc` NULL and status DISCONNECTED, and
     writes an event.
   Replace the Accounts placeholder with connect/disconnect and the connected address.
4. **`invalid_grant`** (Testing-mode 7-day expiry, password change, revoked access), caught in `poll_mail`:
   status DISCONNECTED and `last_error`; a `GMAIL_DISCONNECTED` event; open a `reconnect_gmail` question
   (insert it the way `pipeline.py` inserts `unlock_pdf`); raise an owner alert; stop polling until reconnected.
   The agent's `search_gmail` must then return "Gmail disconnected". Define a `MailDisconnected` exception in
   `app/ingest/mail_source.py` (the agent may import that module, not `pipeline`) and catch it in the tool.
   The owner alert kinds are a CHECK in migration `0005_owner_alert.sql` and `KINDS` in `app/jobs/alerts.py`:
   add a `gmail_disconnected` kind with a new migration, a template in `app/notify/templates.py`, and a line in
   `alerts.alert_line`.
5. **Resume:** reconnecting repeats the connect flow; `_since` already resumes one day before the last sync
   because `sync_state.source` is `'gmail'`.
6. **`mail_source()`**: return `GmailSource` when `MAIL_SOURCE=gmail` and the row is CONNECTED; otherwise raise
   `MailDisconnected` (the poll ends quietly, the planner keeps running).

**Tests to mirror:** `tests/test_eml_folder.py` (list, release by date, search operators), `tests/test_pipeline.py`
(the poll tests from `test_the_stored_email_is_encrypted_at_rest` to `test_an_email_with_no_from_header_is_never_listed`;
an `httpx.MockTransport` example is near line 416), `tests/test_agent_tools.py::test_search_gmail_returns_ids_and_remembers_them`,
`tests/test_web_accounts_settings.py::test_accounts_shows_balances_drift_and_gmail_not_connected`, and
`tests/test_owner_alerts.py` for the new alert kind.

## 3. Google Cloud setup (once)

1. Create a project and enable the **Gmail API**.
2. OAuth consent screen: user type External, status **Testing**, scope **`gmail.readonly` only**, and add the
   demo Gmail account as a **test user**. (Use Internal if the account is on Google Workspace.)
3. Credentials → OAuth client ID → **Web application**, with an authorised redirect URI exactly equal to
   `GOOGLE_REDIRECT_URI` (default `http://localhost:8000/gmail/callback`).
4. Put the client ID and secret in `.env`.

In Testing mode a refresh token **expires after 7 days**: that is the `invalid_grant` path above, and the demo
must reconnect at least weekly.

## 4. Env, import rules and invariants

- **Env** (`.env.example`): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FERNET_KEY` (the
  same key the document store uses), `MAIL_SOURCE=gmail`. Never commit `.env`.
- **Import rules** (`pyproject.toml`, `make test` runs import-linter): `app.agent` must not import
  `app.ingest.pipeline`, `app.jobs`, `app.web` or the ledger writer; `app.ai` and `app.agent` must not import
  `app.notify` or `app.jobs.alerts`; `app.ledger` must not import `app.ingest`; `app.web` must not import
  `app.ai`. Keep `gmail.py` and `gmail_oauth.py` free of `app.ai`. Consider a new contract: `app.agent` and
  `app.ai` never import `app.ingest.gmail` or `app.ingest.gmail_oauth`.
- **Invariants:** the agent never sees a token and reaches mail only through `search_gmail`; read-only scope,
  refused otherwise (the table CHECK is the second wall); polling fetches only known senders; access tokens are
  never written; every email is data, never instructions (scenario 10).

## 5. How to test

- **Offline, a fake Google:** give `GmailSource` and `gmail_oauth` an injectable `httpx` client or
  `googleapiclient` `http`, and drive them with `httpx.MockTransport` (or `googleapiclient.http.HttpMock`)
  returning recorded JSON: `messages.list`, `messages.get` (raw), the token exchange with a wrong scope, and
  a refresh answering `{"error": "invalid_grant"}`. No test may reach Google.
- **Acceptance** (TDD build sequence, phase 8, and CHG-009):
  1. synthetic emails sent to a test Gmail account flow end to end into the ledger;
  2. revoking access produces a Reconnect Gmail item, and the planner keeps running on existing data;
  3. a connection for any scope other than `gmail.readonly` is refused;
  4. the access token is never written anywhere; only the encrypted refresh token is stored.
- **Replay the fixtures through Gmail:** send the files in `fixtures/test_inbox/` and `fixtures/agent_inbox/`
  to the test account (as attachments-preserving forwards or by `messages.import`), including the attacks:
  `12-hidden-urgent.eml` (scenario 10's hidden instruction) and `09-invoice-ashirwad-new-bank.eml` (bank
  details that must wait for the owner, D26). The expected outcomes are in
  `evals/scenarios/*/expected.yaml`.
- **Switching:** `MAIL_SOURCE=eml_folder` (default; every test and eval) or `MAIL_SOURCE=gmail` in `.env`,
  then `make worker`. `make test` must stay offline.

## 6. Open items

- **SMTP for real owner alerts.** `app/notify/smtp.py` and the `send_alert` job are done and tested; with no
  `SMTP_HOST` the alerts wait unsent. Set `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD` and
  `ALERT_FROM` for an account separate from the Gmail being read.
- **Live phase 2 evals, blocked on the Gemini key's daily quota (429).** Done: `docs/evals/2026-10-04-live-pilot/`,
  `2026-10-04-live-after-batch-8/`, and `2026-10-04-live-baseline/` (scenarios 01-07 x 5, then ABORTED). Left,
  each only with the PO's authorisation, in this order:

  ```sh
  # 1. the rest of the 11x5, and 04 again after D28
  uv run python -m evals.runner --ai live --yes-spend --runs 5 --label baseline-part2 \
    --scenario 04-hinglish-voice-note --scenario 08-drift-with-no-explanation \
    --scenario 09-vendor-email-changes-bank-details --scenario 10-hidden-instruction-in-a-vendor-email \
    --scenario 11-shortfall-week
  # 2. one generated page for both invocations
  uv run python -m evals.report combine docs/evals/2026-10-04-live-baseline docs/evals/<date>-live-baseline-part2 --label baseline-11x5
  # 3. the two fortnights, once each
  make workflow AI=live RUN=A ARGS=--yes-spend
  make workflow AI=live RUN=B ARGS=--yes-spend
  # 4. the ablation, one invocation per harness (full, bare, no_planner, no_rule_checks, no_escalation, no_drift_rule)
  uv run python -m evals.ablation --ai live --yes-spend --harness full --label ablation-full
  # 5. the degraded prompt on 01, 07 and 08
  uv run python -m evals.runner --ai live --yes-spend --runs 1 --config evals/variants/prompt-degraded.yaml \
    --label prompt-degraded --scenario 01-debit-alert-for-a-planned-payment \
    --scenario 07-missed-alert-causes-drift --scenario 08-drift-with-no-explanation
  ```

  Each invocation has a hard budget guard (600 calls, 5,000,000 micro-USD). Afterwards: commit the reports,
  run `make check-evidence`, and update `docs/evals/README.md`'s "The live runs, in order".
- **Demo video script:** `docs/demo-script.md`.
- **Known limits in the backlog:** CHG-025 (batch 5 notes: round-off labelling, statement sender, two
  passwords in one email, IFSC-only bank change, unproven multimodal prompts on real Gemini); CHG-026 (a crash
  on an agent run's last attempt can leave a drift case at CHECKING; relative phrasing in plan notes); CHG-037's
  D30 limits (the voice amount check reads form, not meaning; see the README's known limits).
