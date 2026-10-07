# Batch 21 plan: the shrimp-farm live demo profile

PO direction, user-approved (2026-10-07): .po/shrimp-handoff.md with the PO's amendments, which override it.
Deviations D1-D8 were reported before coding and approved, with two PO additions: the explain_credit block shows
the agent's finding (assistant's words, nothing pre-selected), and the event states the gap both ways (short or
over). Dev only; nothing to public (R011, extended). No Gemini until the PO authorises one live rehearsal.

1. CHG-057 (tests first): states.py lets the owner confirm a receivable; reconcile.ask_about_credit at case open;
   repo.credit and the receivables a credit could settle; actions.explain_credit (link: credit MATCHED,
   receivable CONFIRMED, gap stated exactly; not an invoice; stale, settled-meanwhile, helper); the attention page
   and template, with the case's finding; run_case records the final answer on the case; the permission model row.
2. CHG-058: APP_CONFIG_PATH and FIXTURE_REPLIES_PATH settings; scripts/with_env.py and the make targets
   (.env.shrimp, .env.shrimp-fixtures; .env never read or written); fixtures/shrimp_seed.py (refuses any database
   but ./data/shrimp.db), fixtures/shrimp_inbox/, config.shrimp.yaml, fixtures/shrimp_ai_replies.json and
   placeholder uploads; scripts/rehearse_shrimp.py (moves 1-6, fixtures or live under BudgetGuard) writing to a
   git-ignored rehearsals/; docs/demo-shrimp.md.

Gates: make test, lint-imports, make evals --ai fixtures --runs 1 (14/14; its raw-runs output deleted), make
check-evidence; the driver green offline. Then the PO's live authorisation.

## The approved deviations (reported before coding; approved by the PO)

- D1: explain_credit is asked by code when the reconciler opens the case, as ask_about_debit is; the owner can
  answer before or after the agent runs. An agent that ends RESOLVED leaves the credit UNMATCHED and the
  question open; linking closes the case's agent question through _settle_case.
- D2: .env is never read or written. scripts/with_env.py applies .env.shrimp as process environment; the file
  holds no GEMINI_API_KEY or SESSION_SECRET line (a blank one would override .env's). FALLBACK=1 adds
  .env.shrimp-fixtures.
- D3: a fifth party, vendor "Lakshman (caretaker)", for WAGES-OCT26; payment days MON,THU.
- D4: the plan's figures and the early-receipt date are the planner's; the driver checks states, and
  docs/demo-shrimp.md quotes what renders.
- D5: at move 3 the owner REJECTS the dealer's new details (8876), so move 6's NEFT pays the bill.
- D6: FixtureBackend takes an optional store; FIXTURE_REPLIES_PATH points the worker at
  fixtures/shrimp_ai_replies.json, which names its own folders and agent scripts.
- D7: canned replies match uploads by sha256, so the offline runs use PLACEHOLDER files until the user's real
  voice note and photo arrive with their own replies.
- D8: two changes, CHG-057 and CHG-058.
- PO additions: the explain_credit card shows the agent's finding for its case (summary and cited messages,
  escaped, labelled as its words, nothing pre-selected), and the driver checks it renders; the event says
  "short by ₹X" or "over by ₹X", with a test for each.

## Choices made while building (reported to the PO with the offline report)

- explain_credit refuses an invoice the question did not offer (409), not only another business's (404).
- run_case keeps only a final answer code accepted (state["final"]); a refused one is not shown.
- Move 4: the voice note and the photo are one ₹18,000 bill, and the app doesn't see them as duplicates (a voice
  note carries no invoice date), so the owner confirms the voice note's bill and rejects the photo's entry.
- .env.shrimp blanks SMTP_HOST (owner alerts wait unsent) and uses TRACE_DIR=./traces/shrimp.
- Fixture wording: the move-1 "delivery challan" became "Invoice SLAF/INV/0931", because the sort prompt's
  "challan" is a tax challan, which is not extracted; the placeholder transcript says "atharah hazaar", which
  the parser reads ("athaara" it does not).
- A fifth make target, rehearse-shrimp; R011's line names the profile's files; CLAUDE.md names the targets.
- The explain_credit card says "counted in the plan" or "not counted in the plan" for each offered invoice
  (46ea2a2; by the planner's own snapshot since fix round 1).
