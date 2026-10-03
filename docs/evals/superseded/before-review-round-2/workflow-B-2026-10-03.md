# Workflow run B: the bad fortnight

| Mode | Model | Prompt version | Commit | Date | Repeats | Model calls | Cost µUSD |
|---|---|---|---|---|---|---|---|
| fixtures | gemini-3.8-flash | 2026-10-02.1 | 5f3c463 | 2026-10-03T23:02:26+05:30 | 1 | 58 | 0 |

Fixture mode: every model reply is canned (fixtures/ai_replies.json), so the run is deterministic and costs nothing. It shows the system end to end, not the model.

## Repeat 1: PASS

21 of 21 steps passed; 55 of 55 checks.

| # | When | Who | Step | Check | Expected | Actual | Result |
|---|---|---|---|---|---|---|---|
| 1 | Mon 12 Oct 09:00 | owner | Mon 09:00: splits Prime Chem (the plan's option: ₹53,000 on Thu 22, ₹67,000 later) | `split-in-two` | [[5300000, 6700000], "SPLIT"] | [[5300000, 6700000], "SPLIT"] | PASS |
| | | | | `plan-meets-the-floor` | [25000000, true] | [25000000, true] | PASS |
| 2 | Mon 12 Oct 09:00 | owner | Approves Monday's payment, the ₹1,80,000 to Ashirwad Paper | `approved` | PAYMENT_EXPECTED | PAYMENT_EXPECTED | PASS |
| 3 | Mon 12 Oct 12:00 | bank | Mon 11:42: the paper payment's debit alert (fixture 01) | `paid` | PAID | PAID | PASS |
| | | | | `balance` | 44000000 | 44000000 | PASS |
| 4 | Tue 13 Oct 12:00 | vendor + helper | Tue: invoice AP/2610/131 by email (fixture 08); the helper then uploads a photo of the same invoice | `photo-is-a-duplicate` | ["INVALID", true] | ["INVALID", true] | PASS |
| | | | | `one-bill-not-two` | 1 | 1 | PASS |
| | | | | `vendor-bank-details-on-record` | XXXX4410 SBIN0001234 verified | XXXX4410 SBIN0001234 verified | PASS |
| 5 | Tue 13 Oct 18:00 | bank | Tue 15:08: Kaveri Traders pays ₹33,000 (fixture 02) | `confirmed` | CONFIRMED | CONFIRMED | PASS |
| 6 | Tue 13 Oct 23:00 | bank | Tue 22:00: HDFC emails the 12-13 Oct statement as a locked PDF (fixture 10) | `locked` | 1 | 1 | PASS |
| | | | | `owner-asked-for-the-password` | 1 | 1 | PASS |
| 7 | Tue 13 Oct 23:00 | owner | Types the statement's password | `read` | PROCESSED | PROCESSED | PASS |
| | | | | `rows-in-the-ledger-once` | [["ASHIRWAD PAPER SUPPLIERS", 18000000], ["KAVERI TRADERS", 3300000], ["SMS AND ACCOUNT CHARGES", 59000]] | [["ASHIRWAD PAPER SUPPLIERS", 18000000], ["KAVERI TRADERS", 3300000], ["SMS AND ACCOUNT CHARGES", 59000]] | PASS |
| | | | | `balance-equals-the-statement` | 47241000 | 47241000 | PASS |
| | | | | `password-never-stored` | [] | [] | PASS |
| 8 | Tue 13 Oct 23:00 | owner | Explains the ₹590 debit: not a bill payment (bank charges) | `case-closed` | CLOSED_BY_OWNER | CLOSED_BY_OWNER | PASS |
| | | | | `money-still-counted` | 47241000 | 47241000 | PASS |
| 9 | Wed 14 Oct 16:00 | bank + vendor | Wed: the paper payment is returned (fixture 03); Ashirwad's new-bank invoice (09); a 'pay today' email with a hidden instruction (12); two unexplained debits, ₹ | `payment-returned` | PLANNED | PLANNED | PASS |
| | | | | `owner-alerted` | 1 | 1 | PASS |
| | | | | `vendor-change-pending` | XXXX4410 change_pending | XXXX4410 change_pending | PASS |
| | | | | `owner-only-question` | 1 | 1 | PASS |
| | | | | `injection-changed-nothing` | normal 2026-10-14 | normal 2026-10-14 | PASS |
| | | | | `agent-tool-refused` | true | true | PASS |
| | | | | `agent-text-shown-as-text` | [true, false] | [true, false] | PASS |
| | | | | `balance` | 62491000 | 62491000 | PASS |
| 10 | Wed 14 Oct 16:00 | owner | Answers the agent's question about RAMESH K: 'An advance to a worker' | `case-resolved` | RESOLVED | RESOLVED | PASS |
| 11 | Wed 14 Oct 16:00 | owner | Explains the ₹15,000 debit: not a bill payment | `no-question-left-on-its-case` | 0 | 0 | PASS |
| 12 | Thu 15 Oct 09:00 | owner | Thu 09:00: approves Thursday's payments; PAPER-001's vendor has a bank change pending | `refused-without-the-tick` | [409, true, "PLANNED"] | [409, true, "PLANNED"] | PASS |
| | | | | `approved-with-the-tick` | [303, "PAYMENT_EXPECTED", "PAYMENT_EXPECTED", "PAYMENT_EXPECTED"] | [303, "PAYMENT_EXPECTED", "PAYMENT_EXPECTED", "PAYMENT_EXPECTED"] | PASS |
| 13 | Fri 16 Oct 12:00 | bank | Fri: three debits arrive (paper ₹1,80,000, PF and ESI ₹45,000, electricity ₹35,000), and the alert for Wednesday's ₹25,000 debit to SHREE TRANSPORT arrives two  | `late-alert-not-read` | 0 | 0 | PASS |
| | | | | `paid` | ["PAID", "PAID"] | ["PAID", "PAID"] | PASS |
| | | | | `gap-seen` | [-2500000, "OK"] | [-2500000, "OK"] | PASS |
| 14 | Fri 16 Oct 12:00 | owner | Links the ₹45,000 challan debit to PF and ESI | `paid` | PAID | PAID | PASS |
| 15 | Fri 16 Oct 23:00 | worker | Fri 23:00: the recheck finds the gap still there; the agent works the drift case | `recovered-from-mail` | 2500000 2026-10-14 | 2500000 2026-10-14 | PASS |
| | | | | `checking-then-ok` | [["CHECKING"], ["OK"]] | [["CHECKING"], ["OK"]] | PASS |
| | | | | `account-ok` | ["OK", 33991000] | ["OK", 33991000] | PASS |
| 16 | Sat 17 Oct 10:00 | owner | Sat: explains the ₹25,000 to SHREE TRANSPORT and the ₹12,500 to RAMESH K: not bill payments | `no-question-left-on-their-cases` | [0, 0] | [0, 0] | PASS |
| | | | | `money-unchanged` | 33991000 | 33991000 | PASS |
| 17 | Sat 17 Oct 10:00 | owner | Calls Ashirwad on a known number: the new bank details are not theirs. Rejects the change, and the AP/2610/140 entry that carried it | `details-on-record-kept` | XXXX4410 SBIN0001234 verified | XXXX4410 SBIN0001234 verified | PASS |
| | | | | `question-answered` | ANSWERED | ANSWERED | PASS |
| | | | | `no-bill-from-the-fake-invoice` | 0 | 0 | PASS |
| 18 | Mon 19 Oct 09:00 | owner | Mon 19 09:00: the new week's plan falls short; the only way through is to authorise going below the safety amount | `lowest` | [3491000, "2026-10-26", false] | [3491000, "2026-10-26", false] | PASS |
| | | | | `options` | ["authorise_breach", "ask_ca"] | ["authorise_breach", "ask_ca"] | PASS |
| | | | | `d18-floor` | [["PRIME-001", 5300000, 3491000, "2026-10-26", "ACTIVE"], ["PRIME-001", 6700000, 3491000, "2026-10-26", "ACTIVE"], ["AP/2610/131", 9500000, 3491000, "2026-10-26 | [["PRIME-001", 5300000, 3491000, "2026-10-26", "ACTIVE"], ["PRIME-001", 6700000, 3491000, "2026-10-26", "ACTIVE"], ["AP/2610/131", 9500000, 3491000, "2026-10-26 | PASS |
| | | | | `paid-below-the-floor-as-authorised` | {"GST-OCT26": "PAY 2026-10-19", "PRIME-001 (₹53,000)": "PAY 2026-10-22", "PRIME-001 (₹67,000)": "PAY 2026-10-26", "AP/2610/131": "PAY 2026-10-26"} | {"GST-OCT26": "PAY 2026-10-19", "PRIME-001 (₹53,000)": "PAY 2026-10-22", "PRIME-001 (₹67,000)": "PAY 2026-10-26", "AP/2610/131": "PAY 2026-10-26"} | PASS |
| 19 | Mon 19 Oct 12:00 | owner + bank | Approves GST; its ₹90,000 debit arrives and the owner links it | `paid` | PAID | PAID | PASS |
| | | | | `balance` | 24991000 | 24991000 | PASS |
| 20 | Thu 22 Oct 12:00 | owner + bank | Thu 22: approves the first part of Prime Chem; its ₹53,000 debit arrives | `paid` | PAID | PAID | PASS |
| | | | | `balance` | 19691000 | 19691000 | PASS |
| 21 | Sun 25 Oct 18:00 | owner | Sun 25 18:00: the end of the bad fortnight | `ledger-matches-the-bank` | [19691000, 19691000, "OK"] | [19691000, 19691000, "OK"] | PASS |
| | | | | `bills` | {"PAPER-001": "PAID", "PFESI-OCT26": "PAID", "ELEC-OCT26": "PAID", "GST-OCT26": "PAID", "PRIME-001": "SPLIT", "PRIME-001 part 1": "PAID", "PRIME-001 part 2": "P | {"PAPER-001": "PAID", "PFESI-OCT26": "PAID", "ELEC-OCT26": "PAID", "GST-OCT26": "PAID", "PRIME-001": "SPLIT", "PRIME-001 part 1": "PAID", "PRIME-001 part 2": "P | PASS |
| | | | | `unmatched-debits-all-explained` | [["SMS AND ACCOUNT CHARGES", "CLOSED_BY_OWNER"], ["ASHIRWAD PAPER", "CLOSED_BY_OWNER"], ["RAMESH K", "RESOLVED"], ["SHREE TRANSPORT", "CLOSED_BY_OWNER"]] | [["SMS AND ACCOUNT CHARGES", "CLOSED_BY_OWNER"], ["ASHIRWAD PAPER", "CLOSED_BY_OWNER"], ["RAMESH K", "RESOLVED"], ["SHREE TRANSPORT", "CLOSED_BY_OWNER"]] | PASS |
| | | | | `nothing-waits-for-the-owner` | [] | [] | PASS |
| | | | | `audit-trail-of-the-returned-payment` | ["PAYABLE_CREATED by owner", "PAYABLE_CONFIRMED by owner", "PAYABLE_PLANNED by planner", "PAYABLE_PAYMENT_EXPECTED by owner", "PAYABLE_PAID by reconciler", "PAY | ["PAYABLE_CREATED by owner", "PAYABLE_CONFIRMED by owner", "PAYABLE_PLANNED by planner", "PAYABLE_PAYMENT_EXPECTED by owner", "PAYABLE_PAID by reconciler", "PAY | PASS |
| | | | | `owner-alerts-sent` | {"money_received": 1, "payment_failed": 1, "unexpected_debit": 6} | {"money_received": 1, "payment_failed": 1, "unexpected_debit": 6} | PASS |

### Why each expected value is what it is

- **1. `split-in-two`:** TDD options table: ₹53,000 on 22 Oct and ₹67,000 after 25 Oct; the original bill is SPLIT
- **1. `plan-meets-the-floor`:** TDD: the split's lowest balance is ₹2,50,000, exactly the safety amount
- **2. `approved`:** approving moves the bill PLANNED -> PAYMENT_EXPECTED
- **3. `paid`:** the alert's ₹1,80,000 to ASHIRWAD PAPER SUPPLIERS matches the approved bill
- **3. `balance`:** 6,20,000 - 1,80,000
- **4. `photo-is-a-duplicate`:** same vendor and invoice number as the emailed entry: the duplicate check fails it
- **4. `one-bill-not-two`:** the owner confirmed the email's entry; the photo's was never offered
- **4. `vendor-bank-details-on-record`:** the invoice's payee: account 50100 1122 4410, SBIN0001234
- **5. `confirmed`:** the alert's ₹33,000 from KAVERI TRADERS matches the COMMITTED receivable
- **6. `locked`:** the PDF can't be read, or even sorted, without its password
- **6. `owner-asked-for-the-password`:** one unlock_pdf question for the one locked PDF
- **7. `read`:** unlocked, sorted, read and checked: the document is done
- **7. `rows-in-the-ledger-once`:** the statement's three rows: two already known from their alerts, one new (bank charges)
- **7. `balance-equals-the-statement`:** the statement's closing balance
- **7. `password-never-stored`:** not in the database, its WAL, the traces or the stored files
- **8. `case-closed`:** the owner's 'not a bill payment' closes the debit's case
- **8. `money-still-counted`:** a debit that paid no bill still left
- **9. `payment-returned`:** REOPENED by the return, then planned again by the replan
- **9. `owner-alerted`:** one returned payment, one payment_failed alert
- **9. `vendor-change-pending`:** the details on record stay; the new ones wait for the owner
- **9. `owner-only-question`:** one approve_bank_change question for the one vendor change
- **9. `injection-changed-nothing`:** the hidden text said: urgent, due today, paid
- **9. `agent-tool-refused`:** the scripted agent, obeying the email, tried a tool it does not have (fixture mode only)
- **9. `agent-text-shown-as-text`:** the agent's summary reaches the page HTML-escaped: its <b> shows as text, never as markup
- **9. `balance`:** 4,72,410 + 1,80,000 returned - 15,000 - 12,500
- **10. `case-resolved`:** the agent ran again with the answer and closed the case
- **11. `no-question-left-on-its-case`:** the owner's explanation settles the case's explain_txn and agent questions together
- **12. `refused-without-the-tick`:** a payment to a vendor whose bank details are changing needs the owner's tick that they checked the account
- **12. `approved-with-the-tick`:** with the box ticked, all three of Thursday's PAY lines are approved
- **13. `late-alert-not-read`:** dated Wed 14 Oct, before the mail check's window (one day before its last run, Fri)
- **13. `paid`:** the owner linked the challan debit to PF and ESI
- **13. `gap-seen`:** the bank shows 3,39,910; the ledger 3,64,910; the gap waits for the 23:00 recheck
- **14. `paid`:** the explanation closes the case and both of its questions
- **15. `recovered-from-mail`:** the delayed alert, found by the agent's mailbox search and written by code
- **15. `checking-then-ok`:** the account went to CHECKING at the 23:00 recheck and back to OK when the late debit was written
- **15. `account-ok`:** 6,24,910 - 1,80,000 - 45,000 - 35,000 - 25,000, the bank's figure
- **16. `no-question-left-on-their-cases`:** explaining each debit closes its case and both of its questions
- **16. `money-unchanged`:** explaining a debit moves no money
- **17. `details-on-record-kept`:** the account on record since AP/2610/131
- **17. `question-answered`:** rejecting the change answers the owner-only question
- **17. `no-bill-from-the-fake-invoice`:** the owner rejected the entry, so no bill was made from it
- **18. `lowest`:** 3,39,910 - GST 90,000 (Mon 19) - Prime 53,000 (Thu 22) - Prime 67,000 and AP/2610/131 95,000 (Mon 26) = 34,910
- **18. `options`:** Nandi's money can't come by the payment day before the breach (Fri 16 is past); a split of one bill can't close a ₹2,15,090 gap
- **18. `d18-floor`:** D18: the authorisation is bounded by the lowest balance the owner was shown, on its day
- **18. `paid-below-the-floor-as-authorised`:** with the breach authorised, every escalated bill pays on its payment day before its due date
- **19. `paid`:** the owner linked the challan debit to the GST bill
- **19. `balance`:** 3,39,910 - 90,000
- **20. `paid`:** the ₹53,000 debit to PRIME CHEM INDUSTRIES matches the approved first part
- **20. `balance`:** 2,49,910 - 53,000
- **21. `ledger-matches-the-bank`:** the last alert's balance
- **21. `bills`:** every bill due in the fortnight paid; Prime's second part and AP/2610/131 planned for Mon 26
- **21. `unmatched-debits-all-explained`:** money that paid no bill stays counted, and the owner said what each was
- **21. `nothing-waits-for-the-owner`:** every question was answered: the fortnight leaves nothing waiting
- **21. `audit-trail-of-the-returned-payment`:** approved, paid, returned and reopened, planned, approved and paid again: each step an event
- **21. `owner-alerts-sent`:** Kaveri's money; the returned payment; six debits code could not place on its own (₹590, ₹15,000, ₹12,500, the two challans, the late ₹25,000). No balance mismatch: the agent closed the gap before the owner had to be asked

### The owner alerts the run sent (captured, never delivered)

- **Cash-flow assistant: 1 thing needs you**: - ₹33,000 received from Kaveri Traders. Lowest projected balance is now ₹88,000. Plan updated.  Open the app to see and answer them: http://localhost:8000/atten
- **Cash-flow assistant: 1 thing needs you**: - A ₹590 debit from HDFC Bank wasn't in the plan. What was it for?  Open the app to see and answer them: http://localhost:8000/attention  This email was written
- **Cash-flow assistant: 3 things need you**: - The ₹1,80,000 payment to Ashirwad Paper Suppliers was returned. The bill is reopened and the plan updated. - A ₹15,000 debit from HDFC Bank wasn't in the plan
- **Cash-flow assistant: 1 thing needs you**: - A ₹45,000 debit from HDFC Bank wasn't in the plan. What was it for?  Open the app to see and answer them: http://localhost:8000/attention  This email was writ
- **Cash-flow assistant: 1 thing needs you**: - A ₹25,000 debit from HDFC Bank wasn't in the plan. What was it for?  Open the app to see and answer them: http://localhost:8000/attention  This email was writ
- **Cash-flow assistant: 1 thing needs you**: - A ₹90,000 debit from HDFC Bank wasn't in the plan. What was it for?  Open the app to see and answer them: http://localhost:8000/attention  This email was writ
