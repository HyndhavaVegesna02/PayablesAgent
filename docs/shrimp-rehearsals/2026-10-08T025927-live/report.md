# Shrimp rehearsal, live: PASS

- mode: live
- model: gemini-3.8-flash
- prompt_version: 2026-10-04.2
- commit: ed9c2d3
- date: 2026-10-08T02:59:27+05:30
- uploads: ["voice: voice-diesel-raju.mp3", "photo: repair-slip-venkat.jpg"]
- budget: {"calls": 35, "micro_usd": 97755, "rate_limited": 0, "caps": {"calls": 600, "micro_usd": 1000000}, "stopped": null}

## 1. Start, Mon 19 Oct 09:00: the plan before the harvest: PASS

owner, read at Mon 19 Oct 09:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `balance` | 11000000 | 11000000 | PASS | seed: ₹1,10,000 in HDFC **7310 |
| `no-shortfall-yet` | (True, 11000000) | (True, 11000000) | PASS | the ₹2,00,000 advance (COMMITTED, Tue) covers the three bills; the lowest is today's ₹1,10,000 |
| `balance-not-counted` | EXPECTED | EXPECTED | PASS | seed: the ₹10,15,000 balance counts only when it lands or the owner asks for it early |

- plan: {'LEASE-OCT26': 'PAY 2026-10-29', 'APSPDCL-OCT26': 'PAY 2026-10-22', 'WAGES-OCT26': 'PAY 2026-10-22'}

## 2. Move 1, Mon 19 Oct 12:00: the last feed delivery's invoice; the owner confirms ₹25,000: PASS

vendor + owner, read at Mon 19 Oct 12:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `bill-in-the-ledger` | 2500000 | 2500000 | PASS | fixture 01: 10 bags x Rs.2,500.00 = Rs.25,000.00, to the dealer |
| `details-match-the-record` | verified | verified | PASS | fixture 01's account ending 2201 is the one on record: nothing to ask |

## 3. Move 2, Tue 20 Oct 10:00: the advance from RAVI K's personal UPI; the owner links it to HARVEST-ADV: PASS

bank + agent + owner, read at Tue 20 Oct 10:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `payer-unknown` | unknown_txn | unknown_txn | PASS | RAVI K (ravi.k@okaxis) names no party |
| `agent-finding-shown` | True | True | PASS | PO: the explain_credit card shows what the agent found for its case, labelled as its words |
| `nothing-preselected` | False | False | PASS | PO: the AI informs and the owner decides: no invoice is chosen for him |
| `no-bill-from-the-buyer` | (0, 0, True) | (0, 0, True) | PASS | email 02 is the buyer's record: Ravi Traders pays the farm, so nothing from it is payable; a misread entry is rejected, writes nothing, and the plan stays as it was |
| `checklist-5-advance-matched` | ('MATCHED', 2) | ('MATCHED', 2) | PASS | handoff checklist 5: the ₹2,00,000 credit is MATCHED to Ravi Traders |
| `checklist-5-advance-confirmed` | CONFIRMED | CONFIRMED | PASS | handoff checklist 5: HARVEST-ADV is CONFIRMED |
| `linked-to-this-credit` | 1 | 1 | PASS | the receivable names the credit that paid it |
| `balance` | 31000000 | 31000000 | PASS | 1,10,000 + 2,00,000; the alert shows Rs.3,10,000.00 |

- agent (RESOLVED): The credit of ₹2,00,000 on 2026-10-20 (bank_txn:1) is an advance payment from Ravi Traders (Ravi K) for the harvest of 20 October 2026, as confirmed by their purchase record and weighment slip (02-weighment-slip-ravi-traders.eml) and the matching HDFC UPI credit alert (03-credit-ravi-k-upi.eml).
- cited: ravi@ravitraders.example: Purchase record and weighment slip: your harvest of 20 Oct, advance paid; alerts@hdfcbank.example: Credit alert: Rs.2,00,000.00 credited to your account ending 7310
- 02 sorted as payment_confirmation: no bill to reject

## 4. Move 3, Wed 21 Oct 12:00: the ₹6,46,800 settlement with new bank details; the owner confirms the bill, rejects the details, and asks Ravi Traders to pay early: PASS

vendor + owner, read at Wed 21 Oct 12:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `details-held` | change_pending | change_pending | PASS | fixture 04's account 8876 differs from 2201 on record: code holds the old details and asks |
| `bill-in-the-ledger` | 64680000 | 64680000 | PASS | fixture 04: Rs.5,32,800.00 + Rs.1,14,000.00 |
| `shortfall` | False | False | PASS | ₹3,10,000 cannot pay ₹6,46,800 + ₹25,000 on Mon 26 before the ₹10,15,000 balance is expected on Fri 30 |
| `ask-ravi-early-offered` | 1 | 1 | PASS | the shortfall options include asking for HARVEST-BAL early |
| `old-details-kept` | ('XXXX2201', 'SBIN0004321', 'verified') | ('XXXX2201', 'SBIN0004321', 'verified') | PASS | D5: the owner rejects 8876 (he checked by phone); 2201 stays on record |
| `asked-not-counted` | EXPECTED | EXPECTED | PASS | D13: asking a customer to pay early changes no ledger row; the money counts when it lands |

- plan: lowest -₹4,66,800 on 2026-10-29; {'LEASE-OCT26': 'PAY 2026-10-29', 'APSPDCL-OCT26': 'PAY 2026-10-22', 'WAGES-OCT26': 'PAY 2026-10-22', 'SLAF/INV/0931': 'PAY 2026-10-26', 'SLAF/INV/1042': 'ESCALATE'}
- early-receipt option: {"amount_paise":101500000,"from_date":"2026-10-30","receivable_id":2,"to_date":"2026-10-21"}, lowest ₹5,48,200, meets the rule: True

## 5. Move 4, Thu 22 Oct 10:00: the lease asked early; the caretaker's Telugu voice note (₹3,000 diesel) and a photo of Venkat Motors' ₹18,000 repair slip; the owner confirms both bills and approves Thursday's payments: PASS

landowner + helper + owner, read at Thu 22 Oct 10:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `lease-not-paid-early` | ('2026-10-31', False) | ('2026-10-31', False) | PASS | the landowner's email changes no bill: the lease stays due Sat 31 Oct |
| `two-bills-not-one` | ['passed', 'passed'] | ['passed', 'passed'] | PASS | the delta: a ₹3,000 diesel bill and an ₹18,000 repair are two bills, so neither is a duplicate |
| `transcript-beside-it` | True | True | PASS | the voice entry shows what was said beside the bill |
| `voice-bill` | (True, None) | (True, None) | PASS | the delta: 'Raju petrol bunk diesel bill ... three thousand rupees, twenty-fourth October 2026'; found by its ₹3,000 and 24 Oct, the vendor compared as the app compares names |
| `slip-bill` | (True, 'VM412') | (True, 'VM412') | PASS | the delta's slip: VM/412, Rs. 14,000 + Rs. 4,000 = Rs. 18,000, pay by 25/10/2026; the vendor as the app matches names (it contains 'Venkat Motors': live read the whole header line) |
| `new-bills-in-the-plan` | (('PAY 2026-10-22', True), ('PAY 2026-10-22', True)) | (('PAY 2026-10-22', True), ('PAY 2026-10-22', True)) | PASS | the planner's own decision and reason (PO): both fall due before the next payment day, Mon 26, so each is paid today, Thu 22, its 'latest payment day on or before the due date'; the shortfall is the dealer's ₹6,46,800 (ESCALATE), not these |
| `thursday-approved` | ('PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED') | ('PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED') | PASS | the owner approves the plan's four PAY lines for Thu 22 (APSPDCL, the wages, the diesel and the repair, ₹51,000), so each is paid by its due date; the money moves only in his bank app |

- lease: PAY 2026-10-29
- transcript: Raju petrol bunk diesel bill generator kosam 3000 rupees 24th October 2026 lopala kattali
- vendors as read: 'Raju petrol bunk'; 'VENKAT MOTORS / Aerator & Pump Repairs, Bhimavaram'
- plan: {'LEASE-OCT26': 'PAY 2026-10-29', 'APSPDCL-OCT26': 'PAY 2026-10-22', 'WAGES-OCT26': 'PAY 2026-10-22', 'SLAF/INV/0931': 'PAY 2026-10-26', 'SLAF/INV/1042': 'ESCALATE', 'Raju petrol bunk': 'PAY 2026-10-22', 'VM/412': 'PAY 2026-10-22'}

## 6. Move 5, Fri 23 Oct 16:00: Ravi Traders pays the balance ₹95,000 short; the owner links it to HARVEST-BAL and approves Monday's payments: PASS

bank + agent + owner, read at Fri 23 Oct 16:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `payer-matches-amount-doesnt` | ambiguous_match | ambiguous_match | PASS | RAVI TRADERS names Ravi Traders, but ₹9,20,000 is no open invoice's amount |
| `agent-finding-shown` | True | True | PASS | PO: the explain_credit card shows what the agent found for its case, labelled as its words |
| `nothing-preselected` | False | False | PASS | PO: the AI informs and the owner decides: no invoice is chosen for him |
| `no-bill-from-the-buyer` | (0, 0, True) | (0, 0, True) | PASS | email 06 is the buyer's record: Ravi Traders pays the farm, so nothing from it is payable; a misread entry is rejected, writes nothing, and the plan stays as it was |
| `checklist-5-balance-confirmed` | ('CONFIRMED', 2) | ('CONFIRMED', 2) | PASS | handoff checklist 5: HARVEST-BAL is CONFIRMED with the ₹9,20,000 credit |
| `checklist-5-gap-named` | True | True | PASS | handoff checklist 5: the event names the gap: 10,15,000 - 9,20,000 = 95,000 |
| `checklist-5-floor-holds` | (True, True) | (True, True) | PASS | handoff checklist 5: the plan's lowest balance is at or above the ₹50,000 safety amount |
| `dealer-approved` | PAYMENT_EXPECTED | PAYMENT_EXPECTED | PASS | the owner approves Monday's payments, the dealer's settlement among them |

- agent (RESOLVED): Bank transaction bank_txn:2 (credit of Rs.9,20,000 on 2026-10-23, reference N296271234567) settles Receivable 2 (HARVEST-BAL, expected Rs.10,15,000). The payment advice from Ravi Traders confirms this NEFT payment of Rs.9,20,000 is for the harvest balance payable to Godavari Aqua Farm, matching the credit alert for account ending 7310.
- cited: ravi@ravitraders.example: Payment advice - harvest balance, Godavari Aqua Farm; alerts@hdfcbank.example: Credit alert: Rs.9,20,000.00 credited to your account ending 7310
- 06 sorted as payment_confirmation: no bill to reject
- event: Owner: this ₹9,20,000 credit settles Ravi Traders HARVEST-BAL, short by ₹95,000 (₹10,15,000 invoiced).
- plan: lowest ₹4,32,200 on 2026-10-29; {'LEASE-OCT26': 'PAY 2026-10-29', 'SLAF/INV/0931': 'PAY 2026-10-26', 'SLAF/INV/1042': 'PAY 2026-10-26'}

## 7. Move 6, Mon 26 Oct 11:00: the dealer's NEFT lands; the bill is paid: PASS

bank, read at Mon 26 Oct 11:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `dealer-paid` | PAID | PAID | PASS | fixture 08's ₹6,46,800 NEFT to SRI LAKSHMI AQUA FEEDS matches the approved bill |
| `balance` | 58320000 | 58320000 | PASS | 12,30,000 - 6,46,800; the alert shows Rs.5,83,200.00 |
