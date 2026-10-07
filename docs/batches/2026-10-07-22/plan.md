# Batch 22 plan: the shrimp demo's move 4 as two bills

The user's delta to the shrimp-demo handoff, pasted into the dev session on 2026-10-07; the user chose "build it
as batch 22, plan to the PO first". PO approved, with E1-E4 and two notes. Dev only (R011); offline only; no Gemini.

1. CHG-060 (tests first):
   - fixtures/shrimp_ai_replies.json: the PLACEHOLDER voice note's reply becomes Raju Petrol Bunk's ₹3,000 diesel
     bill (the delta's script as transcript, amount_spoken "three thousand", due 2026-10-24); the PLACEHOLDER
     slip's becomes Venkat Motors VM/412, ₹14,000 + ₹4,000 = ₹18,000, due 2026-10-25.
   - scripts/rehearse_shrimp.py: the user's file names become voice-diesel-raju and repair-slip-venkat; move 4
     confirms both bills and rejects nothing, and pins what the planner decides for each (PO note 1).
   - docs/demo-shrimp.md: move 4 and the files to supply rewritten; the "atharah hazaar" note goes.
   - tests/test_shrimp_profile.py: the names, the move-4 checks and the quotes.

## Deviations from the delta (approved by the PO)

- E1: the move-4 command is `make demo-time-shrimp T=...`; plain demo-time reads .env's settings.
- E2: the ₹50,000 floor is checked after move 5, not move 4: at move 4 the dealer's ₹6,46,800 still leaves the
  plan short (ESCALATE) until the harvest balance lands.
- E3: offline keeps the PLACEHOLDER files, with the new replies, until the real recordings arrive; their own
  replies are added then, under their names.
- E4: CHG-059 (the deferred minors and the `shortfall` rename) and the delta's optional Telugu number words stay
  out of this batch.
- PO note 2: the delta's conditional "or Telugu" in the voice prompt, if ever needed, is a separate shrimp-only
  prompt file referenced from config.shrimp.yaml alone, with its own version and the PO's go; never an edit to a
  prompt file the committed evals use. Not in this batch.

Gates: make test and make check-evidence, or, while Application Control blocks make, their direct commands
(pytest, lint-imports, scripts/check_evidence.py) recorded as such; the offline driver green; no protected path
changes. Then the review, then the PO's verdict.
