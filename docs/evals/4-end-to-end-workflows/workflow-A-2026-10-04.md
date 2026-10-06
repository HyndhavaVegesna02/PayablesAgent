# Workflow run A: the worked example's fortnight

| Mode | Model | Prompt version | Commit | Date | Repeats | Model calls | Cost µUSD |
|---|---|---|---|---|---|---|---|
| fixtures | gemini-3.8-flash | 2026-10-04.2 | cf733c3 | 2026-10-04T18:00:47+05:30 | 1 | 37 | 0 |

Fixture mode: every model reply is canned (fixtures/ai_replies.json), so the run is deterministic and costs nothing. It shows the system end to end, not the model.

## Repeat 1: PASS

19 of 19 steps passed; 57 of 57 checks.

| # | When | Who | Step | Check | Expected | Actual | Result |
|---|---|---|---|---|---|---|---|
| 1 | Mon 12 Oct 09:00 | owner | Opens the week page: Monday's 14-day plan | `lowest-balance` | 18300000 | 18300000 | PASS |
| | | | | `lowest-on` | 2026-10-22 | 2026-10-22 | PASS |
| | | | | `plan-flags-the-shortfall` | false | false | PASS |
| | | | | `decisions` | {"PAPER-001": "PAY 2026-10-12", "PFESI-OCT26": "PAY 2026-10-15", "ELEC-OCT26": "PAY 2026-10-15", "GST-OCT26": "PAY 2026-10-19", "PRIME-001": "ESCALATE"} | {"PAPER-001": "PAY 2026-10-12", "PFESI-OCT26": "PAY 2026-10-15", "ELEC-OCT26": "PAY 2026-10-15", "GST-OCT26": "PAY 2026-10-19", "PRIME-001": "ESCALATE"} | PASS |
| | | | | `golden-balances-on-the-page` | [true, true, true, true, true] | [true, true, true, true, true] | PASS |
| | | | | `options` | [["early_receipt", 38300000, 1], ["split", 25000000, 1], ["authorise_breach", 18300000, 0]] | [["early_receipt", 38300000, 1], ["split", 25000000, 1], ["authorise_breach", 18300000, 0]] | PASS |
| 2 | Mon 12 Oct 09:00 | owner | Chooses 'Ask Nandi Foods to pay ₹2,00,000 by Fri 16 Oct' | `chosen` | 1 | 1 | PASS |
| | | | | `nothing-counted-yet` | EXPECTED | EXPECTED | PASS |
| 3 | Mon 12 Oct 09:00 | owner | Approves Monday's payment: the ₹1,80,000 to Ashirwad Paper | `approved` | PAYMENT_EXPECTED | PAYMENT_EXPECTED | PASS |
| | | | | `approved-by-the-owner` | 1 | 1 | PASS |
| | | | | `first-approval-not-stale` | false | false | PASS |
| 4 | Mon 12 Oct 12:00 | bank | Mon 11:42: HDFC's debit alert for the paper payment (fixture 01) | `bill-paid` | PAID | PAID | PASS |
| | | | | `balances-agree` | [44000000, "OK"] | [44000000, "OK"] | PASS |
| 5 | Tue 13 Oct 12:00 | vendor | Tue 11:05: Ashirwad emails invoice AP/2610/131 with its PDF (fixture 08) | `waits-for-the-owner` | VALID | VALID | PASS |
| | | | | `not-in-the-plan-yet` | false | false | PASS |
| 6 | Tue 13 Oct 18:00 | bank | Tue 15:08: Kaveri Traders pays ₹33,000 (fixture 02) | `receipt-confirmed` | CONFIRMED | CONFIRMED | PASS |
| | | | | `balance` | 47300000 | 47300000 | PASS |
| 7 | Wed 14 Oct 11:00 | helper | Wed: uploads Shree Ganesh's handwritten bill (photo) | `read` | 1239000 | 1239000 | PASS |
| 8 | Wed 14 Oct 11:00 | helper | Uploads a voice note: 'Sharma Packaging ka bill, dedh lakh rupaye, paanch November' | `dedh-lakh-read-by-code` | 15000000 | 15000000 | PASS |
| | | | | `due-date-flagged-not-guessed` | AWAITING_OWNER failed: no due date was given: fill it in | AWAITING_OWNER failed: no due date was given: fill it in | PASS |
| 9 | Wed 14 Oct 11:00 | helper | Types a bill: Laxmi Transport LT/2610/88, ₹18,000, due Mon 2 Nov | `four-channels-waiting` | ["email", "photo", "voice", "typed"] | ["email", "photo", "voice", "typed"] | PASS |
| | | | | `helper-cannot-confirm` | [403, true] | [403, true] | PASS |
| 10 | Thu 15 Oct 09:30 | owner | Thu 09:30: approves Thursday's payments (PF and ESI, electricity) | `stale-plan-refused-first` | true | true | PASS |
| | | | | `approved` | ["PAYMENT_EXPECTED", "PAYMENT_EXPECTED"] | ["PAYMENT_EXPECTED", "PAYMENT_EXPECTED"] | PASS |
| 11 | Thu 15 Oct 12:00 | bank | Thu 10:05 and 10:20: debits of ₹45,000 (EPFO ESIC CHALLAN) and ₹35,000 (electricity) | `electricity-paid` | PAID | PAID | PASS |
| | | | | `pf-esi-paid-by-its-payee-words` | PAID | PAID | PASS |
| | | | | `no-case-for-the-challan` | 0 | 0 | PASS |
| | | | | `balance` | 39300000 | 39300000 | PASS |
| 12 | Fri 16 Oct 12:00 | bank | Fri 10:12: Nandi Foods pays ₹2,00,000 early (fixture 07) | `receipt-confirmed` | CONFIRMED | CONFIRMED | PASS |
| | | | | `lowest-balance-now` | 38300000 | 38300000 | PASS |
| | | | | `prime-chem-pay-thursday` | PAY 2026-10-22 | PAY 2026-10-22 | PASS |
| | | | | `plan-valid` | true | true | PASS |
| | | | | `explain-plan-note` | [true, true] | [true, true] | PASS |
| 13 | Sat 17 Oct 10:00 | owner | Sat: confirms the four new bills on Needs attention, typing in the voice note's due date (Thu 5 Nov) and whatever else the page marks | `due-date-marked-on-the-form` | true | true | PASS |
| | | | | `bills-in-the-ledger` | ["", "418", "AP/2610/131", "LT/2610/88"] | ["", "418", "AP/2610/131", "LT/2610/88"] | PASS |
| | | | | `new-decisions` | {"418": "PAY 2026-10-22", "AP/2610/131": "PAY 2026-10-26", "LT/2610/88": "WAIT", "voice bill (1,50,000, due 5 Nov)": "WAIT"} | {"418": "PAY 2026-10-22", "AP/2610/131": "PAY 2026-10-26", "LT/2610/88": "WAIT", "voice bill (1,50,000, due 5 Nov)": "WAIT"} | PASS |
| | | | | `prime-chem-still-thursday` | PAY 2026-10-22 | PAY 2026-10-22 | PASS |
| | | | | `lowest` | [27561000, "2026-10-26"] | [27561000, "2026-10-26"] | PASS |
| | | | | `first-bank-details-asked` | [1] | [1] | PASS |
| 14 | Sat 17 Oct 10:00 | owner | Calls Ashirwad on a known number: account 4410 is theirs. Approves the bank details | `bank-details-on-record` | XXXX4410 SBIN0001234 verified | XXXX4410 SBIN0001234 verified | PASS |
| 15 | Mon 19 Oct 09:30 | owner | Mon 19 09:30: approves Monday's payment (GST) | `approved` | PAYMENT_EXPECTED | PAYMENT_EXPECTED | PASS |
| 16 | Mon 19 Oct 12:00 | bank + owner | Mon 10:10: ₹90,000 'NETBANKING TAX PAYMENT' names no tax office; the owner answers which bill it paid: GST | `gst-debit-needs-the-owner` | REVIEW | REVIEW | PASS |
| | | | | `gst-paid` | PAID | PAID | PASS |
| | | | | `no-question-left-for-the-debit` | 0 | 0 | PASS |
| | | | | `balance` | 50300000 | 50300000 | PASS |
| 17 | Thu 22 Oct 09:30 | owner | Thu 22 09:30: approves Thursday's payments (Prime Chem, Shree Ganesh) | `approved` | ["PAYMENT_EXPECTED", "PAYMENT_EXPECTED"] | ["PAYMENT_EXPECTED", "PAYMENT_EXPECTED"] | PASS |
| 18 | Thu 22 Oct 12:00 | bank | Thu 10:15 and 10:31: ₹1,20,000 to Prime Chem, ₹12,390 to Shree Ganesh | `paid` | ["PAID", "PAID"] | ["PAID", "PAID"] | PASS |
| | | | | `balance-after-prime-chem` | 38300000 | 38300000 | PASS |
| | | | | `balance` | 37061000 | 37061000 | PASS |
| 19 | Sun 25 Oct 18:00 | owner | Sun 25 18:00: the end of the fortnight | `every-due-bill-paid` | {"PAPER-001": "PAID", "PFESI-OCT26": "PAID", "ELEC-OCT26": "PAID", "GST-OCT26": "PAID", "PRIME-001": "PAID", "418": "PAID"} | {"PAPER-001": "PAID", "PFESI-OCT26": "PAID", "ELEC-OCT26": "PAID", "GST-OCT26": "PAID", "PRIME-001": "PAID", "418": "PAID"} | PASS |
| | | | | `receipts` | ["CONFIRMED", "CONFIRMED"] | ["CONFIRMED", "CONFIRMED"] | PASS |
| | | | | `ledger-matches-the-bank` | [37061000, 37061000, "OK"] | [37061000, 37061000, "OK"] | PASS |
| | | | | `no-unmatched-money` | 0 | 0 | PASS |
| | | | | `owner-alerts-sent` | [["money_received", "receivable:1"], ["money_received", "receivable:2"], ["unexpected_debit", "bank_txn:6"]] | [["money_received", "receivable:1"], ["money_received", "receivable:2"], ["unexpected_debit", "bank_txn:6"]] | PASS |
| | | | | `tdd-money-received-message` | true | true | PASS |
| | | | | `alerts-go-to-the-owner-only` | ["owner@example.test"] | ["owner@example.test"] | PASS |
| | | | | `audit-trail-email-to-bill-to-plan` | {"email": "email invoice PROCESSED", "candidate": "ACCEPTED", "bill-from-that-email": true, "bill-events": ["PAYABLE_CREATED by owner", "PAYABLE_CONFIRMED by ow | {"email": "email invoice PROCESSED", "candidate": "ACCEPTED", "bill-from-that-email": true, "bill-events": ["PAYABLE_CREATED by owner", "PAYABLE_CONFIRMED by ow | PASS |

### Why each expected value is what it is

- **1. `lowest-balance`:** TDD worked example: ₹6,20,000 less the five bills, plus Kaveri's ₹33,000, falls to ₹1,83,000 when Prime Chem is paid on Thu 22 Oct
- **1. `lowest-on`:** TDD: Thu 22 Oct, the Prime Chem payment day
- **1. `plan-flags-the-shortfall`:** ₹1,83,000 is ₹67,000 below the ₹2,50,000 safety amount
- **1. `decisions`:** TDD: the four earlier payments PAY on the payment day before each is due; Prime Chem ESCALATE
- **1. `golden-balances-on-the-page`:** TDD golden table, original plan: Mon 4,40,000, Tue 4,73,000, Thu 3,93,000, Mon 3,03,000, Thu 1,83,000
- **1. `options`:** TDD options table: Nandi early ₹3,83,000 (meets); split Prime Chem ₹2,50,000 (meets, exactly); authorise the breach ₹1,83,000 (does not)
- **2. `chosen`:** the owner's choice is recorded on the option
- **2. `nothing-counted-yet`:** TDD: the owner asks Nandi; the money counts when it arrives, not when asked
- **3. `approved`:** approving tells the plan to expect it
- **3. `approved-by-the-owner`:** app_user 1 is the owner
- **3. `first-approval-not-stale`:** Monday's plan is today's plan
- **4. `bill-paid`:** the alert's ₹1,80,000 to ASHIRWAD PAPER SUPPLIERS matches the approved bill by amount, date and name
- **4. `balances-agree`:** 6,20,000 - 1,80,000; the alert shows Rs.4,40,000.00
- **5. `waits-for-the-owner`:** read and every check passed (GSTIN, arithmetic, dates); a bill waits for the owner
- **5. `not-in-the-plan-yet`:** an unconfirmed bill is not planned
- **6. `receipt-confirmed`:** TDD: matched and CONFIRMED
- **6. `balance`:** golden table, Tue 13 Oct
- **7. `read`:** the bill's total: 10,000 + 500 + CGST 945 + SGST 945
- **8. `dedh-lakh-read-by-code`:** 'dedh lakh' is 1.5 lakh; code reads the spoken words, not a model's figure
- **8. `due-date-flagged-not-guessed`:** 'paanch November' has no year: the date is left for the owner, never guessed (CHG-030)
- **9. `four-channels-waiting`:** one bill from each channel, all waiting for the owner
- **9. `helper-cannot-confirm`:** confirming is owner-only: the role check refuses a logged-in helper with a valid token
- **10. `stale-plan-refused-first`:** the plan on screen was made on Wednesday; approving it on Thursday is refused and the page shows today's plan
- **10. `approved`:** both approved for Thu 15 Oct
- **11. `electricity-paid`:** amount, date and name match
- **11. `pf-esi-paid-by-its-payee-words`:** D27: 'EPFO ESIC CHALLAN' names the PF and ESI payee words, with the bill's amount and date
- **11. `no-case-for-the-challan`:** code placed it, so neither the agent nor the owner is asked
- **11. `balance`:** golden table, Thu 15 Oct; the alert shows Rs.3,93,000.00
- **12. `receipt-confirmed`:** TDD: matched and CONFIRMED
- **12. `lowest-balance-now`:** TDD: the planner reruns and the lowest balance becomes ₹3,83,000 (golden table, Thu 22 Oct)
- **12. `prime-chem-pay-thursday`:** TDD: Prime Chem moves to PAY on Thu 22 Oct
- **12. `plan-valid`:** ₹3,83,000 is above the ₹2,50,000 safety amount
- **12. `explain-plan-note`:** a 'what changed' note is on the plan; offline it is code's template (the fixture AI has no canned note); live, Gemini's, or the template when Gemini's fails its check
- **13. `due-date-marked-on-the-form`:** the empty field is marked on the page, not left to fail on Confirm
- **13. `bills-in-the-ledger`:** AP/2610/131 (email), 418 (photo), the voice note's bill (no number said), LT/2610/88 (typed)
- **13. `new-decisions`:** 418 due Sat 24 Oct: paid Thu 22; AP/2610/131 due Wed 28: paid Mon 26; LT/2610/88 (due 2 Nov) and Sharma (due 5 Nov) are after the horizon, Sat 17 to Fri 30 Oct
- **13. `prime-chem-still-thursday`:** the new bills still leave the floor clear
- **13. `lowest`:** 5,93,000 - GST 90,000 - Prime 1,20,000 - 418 12,390 - AP/2610/131 95,000 = 2,75,610, on Mon 26
- **13. `first-bank-details-asked`:** D26: AP/2610/131 is Ashirwad's first bill with bank details; confirming it doesn't approve them, so the owner is asked
- **14. `bank-details-on-record`:** stored only once the owner approved them
- **15. `approved`:** approving moves the bill PLANNED -> PAYMENT_EXPECTED (the state the owner's approval means)
- **16. `gst-debit-needs-the-owner`:** no statutory payee word in the description, so code can't place it and asks (CHG-028's fallback)
- **16. `gst-paid`:** the owner linked the debit to the GST bill: PAID
- **16. `no-question-left-for-the-debit`:** the case is settled, so neither of its questions still waits (CHG-027 fix)
- **16. `balance`:** golden table (Nandi paid), Mon 19 Oct
- **17. `approved`:** both are the plan's PAY lines for Thu 22 Oct; approving moves each to PAYMENT_EXPECTED
- **18. `paid`:** each debit's amount, date and payee name match its approved bill
- **18. `balance-after-prime-chem`:** the TDD's ₹3,83,000 on Thu 22 Oct, now the bank's own figure
- **18. `balance`:** 3,83,000 - 12,390
- **19. `every-due-bill-paid`:** each was approved and its debit matched or linked during the fortnight
- **19. `receipts`:** Kaveri's ₹33,000 on Tue 13 and Nandi's ₹2,00,000 on Fri 16 both arrived and matched
- **19. `ledger-matches-the-bank`:** the last alert's balance
- **19. `no-unmatched-money`:** every debit and credit was matched to a bill or a receipt, by code or by the owner
- **19. `owner-alerts-sent`:** Kaveri's and Nandi's money arriving; the tax debit code could not place
- **19. `tdd-money-received-message`:** TDD Messages table: '₹2,00,000 received from Nandi Foods. Lowest projected balance is now ₹3.83L. Plan updated.'
- **19. `alerts-go-to-the-owner-only`:** the recipient comes from the database: the owner's login
- **19. `audit-trail-email-to-bill-to-plan`:** the stored email, the entry read from it, the bill the owner confirmed from that entry, each change as an event, the plan line

### The owner alerts the run sent (captured, never delivered)

- **Cash-flow assistant: 1 thing needs you**: - ₹33,000 received from Kaveri Traders. Lowest projected balance is now ₹1,83,000. Plan updated.  Open the app to see and answer them: http://localhost:8000/att
- **Cash-flow assistant: 1 thing needs you**: - ₹2,00,000 received from Nandi Foods. Lowest projected balance is now ₹3,83,000. Plan updated.  Open the app to see and answer them: http://localhost:8000/atte
- **Cash-flow assistant: 1 thing needs you**: - A ₹90,000 debit from HDFC Bank wasn't in the plan. What was it for?  Open the app to see and answer them: http://localhost:8000/attention  This email was writ
