# Batch 23 plan: the shrimp rehearsal holds under live variance

Live rehearsal 1 (2026-10-07T235555, $0.22) read the user's voice note and slip correctly and played both credit
moments live; moves 3-6 went red on a driver defect and one name check. The PO approved CHG-061 (2026-10-08),
offline only, tests first, dev only.

1. CHG-061 (tests first):
   - scripts/rehearse_shrimp.py: every bill found by its content (amount and invoice number), every question by
     its subject. A waiting "bill" from Ravi Traders (the buyer) is rejected through the real form, with checks
     that no payable was made and the plan is unaffected; the report notes which path happened. slip-bill and
     voice-bill compare vendors with the app's own name_matches.
   - fixtures/shrimp_inbox/02 and 06: first lines say they are the buyer's records (Ravi Traders pays the farm,
     nothing payable by the farm); 02's advance line and 06's net in those lines. Canned replies unchanged
     (matched by each file's text, which the backend reads at start).
   - fixtures/shrimp_ai_replies.json: the user's real files' replies, live rehearsal 1's verbatim extractions.
   - docs/demo-shrimp.md: reject the misread slip if it appears; the owner may tidy the slip's vendor name.
   - tests/test_shrimp_profile.py: the content lookups, both 02 paths, the name comparison, the real-file
     replies; tests pin the placeholders so they never depend on the untracked files.

Checked before building (PO's precondition): rejecting an email-read entry is the existing reject_candidate
(any VALID or AWAITING_OWNER entry; it closes its confirm_record question and withdraws its bank proposals;
tests/test_batch8_review_fixes.py rejects an email entry). No app change needed.

Gates: make test and make check-evidence, or their direct commands while make is blocked, recorded as such;
evals --ai fixtures --runs 1 (its raw-runs folder deleted); the offline driver green. Then the review and the PO's
verdict; then the PO authorises live rehearsal 2 (cap $1.00).
