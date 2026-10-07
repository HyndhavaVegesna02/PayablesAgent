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
