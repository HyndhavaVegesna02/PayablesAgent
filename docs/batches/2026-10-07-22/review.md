# Batch 22 review: the shrimp demo's move 4 as two bills (CHG-060)

One yt-reviewer read the batch, range d5c1456..dff9eaf, then the fix round.

## Round 1 (dff9eaf): FIX_REQUIRED

AC1-AC4 met offline; no protected path, prompt file or app/ change; every quote renders and is in the doc; the
pre-patch replay fails for the right reasons; the doc's E2 floor claim, the planner's decision for the two bills
and the Thursday-to-Monday claim all match the plan's own lines. One major:

- **Move 4 looked its bills up by the exact vendor name a model read.** Live, the slip says "VENKAT MOTORS" and the
  transcript "Raju petrol bunk"; the ledger treats those as one name with the expected ones, but the driver's SQL
  `pt.name = ?` and `lines.get(name)` did not, so a correct live run would go red on move 4 (probed in-process
  with "VENKAT MOTORS": "expected one bill from Venkat Motors, found 0"). evals/workflow_runs.py's
  decision_by_amount (CHG-045) exists for exactly this.

Minors: bill_of's `-> tuple | None` never returns None; DIESEL/REPAIR and the *_SAID dicts stated the same facts
twice; the planner's reason was narrated, not checked; the doc's move 5 didn't say Thursday's four, unapproved,
are paid late on Monday.

## Fix round 1 (05a0f16)

planned_bill() finds each bill by amount and due date, joined to the current plan's line, compares the vendor
and number as the app does (normalise_name, normalise_invoice_number), and checks the planner's reason ("latest
payment day on or before the due date"). DIESEL and REPAIR are the one source for the checks and the owner's
typing. A test plays the fortnight with "VENKAT MOTORS" and "raju petrol bunk". The doc says the four are paid
late on Monday, and that approving them at move 4 pays them on time.

## Round 2 (05a0f16): APPROVE

The spelling test fails on dff9eaf's driver with the round-1 message and passes now; the reason literal matches
app/planner/plan.py:197; approving Thursday's payments at the end of move 4 was probed in-process (303; the four
go to PAYMENT_EXPECTED; the fortnight still passes 7/7), so the doc's claim is true. One minor left, to CHG-059:
the slip-bill check writes normalise_invoice_number("VM/412") instead of REPAIR's field.

## After the review: the PO's narrative choice (06f41e8)

On the reviewer's minor about Thursday's four being paid late, the PO chose: the owner approves Thursday's
payments at move 4 (APSPDCL, the wages, the diesel and the repair, ₹51,000), so they are paid on time and the
approval card is seen on stage. The driver checks all four PAYMENT_EXPECTED; move 5 approves only the dealer's
two; the floor (₹4,32,200) and move 6 are unchanged. Close gates rerun at 06f41e8 (direct-gates-final.txt).

## Verdict

PO (payablesagent-ac), 2026-10-07: CHG-060 ACCEPTED, on its own direct run at 73abb8a in
C:\Hyn\PayablesAgent-uicheck with no Gemini: pytest 1968 passed; the offline driver 7/7 (move 4 confirms both
bills and approves Thursday's payments); a clean tree and a diff limited to docs/demo-shrimp.md,
fixtures/shrimp_ai_replies.json, scripts/rehearse_shrimp.py and tests/test_shrimp_profile.py. make stayed
blocked by Application Control; its red entries stay. Push authorised: dev to origin main (with d5c1456's
backlog fix); the public and submission repositories untouched. The live rehearsal waits for the user's real
voice note and photo and the billing headroom.
