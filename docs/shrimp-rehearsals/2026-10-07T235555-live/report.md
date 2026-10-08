# Shrimp rehearsal, live: FAIL

- mode: live
- model: gemini-3.8-flash
- prompt_version: 2026-10-04.2
- commit: 9feec65+uncommitted
- date: 2026-10-07T23:55:55+05:30
- uploads: ["voice: voice-diesel-raju.mp3", "photo: repair-slip-venkat.jpg"]
- budget: {"calls": 45, "micro_usd": 217417, "rate_limited": 0, "caps": {"calls": 600, "micro_usd": 1000000}, "stopped": null}

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

bank + agent + owner, read at Tue 20 Oct 10:01

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `payer-unknown` | unknown_txn | unknown_txn | PASS | RAVI K (ravi.k@okaxis) names no party |
| `agent-finding-shown` | True | True | PASS | PO: the explain_credit card shows what the agent found for its case, labelled as its words |
| `nothing-preselected` | False | False | PASS | PO: the AI informs and the owner decides: no invoice is chosen for him |
| `checklist-5-advance-matched` | ('MATCHED', 2) | ('MATCHED', 2) | PASS | handoff checklist 5: the ₹2,00,000 credit is MATCHED to Ravi Traders |
| `checklist-5-advance-confirmed` | CONFIRMED | CONFIRMED | PASS | handoff checklist 5: HARVEST-ADV is CONFIRMED |
| `linked-to-this-credit` | 1 | 1 | PASS | the receivable names the credit that paid it |
| `balance` | 31000000 | 31000000 | PASS | 1,10,000 + 2,00,000; the alert shows Rs.3,10,000.00 |

- agent (RESOLVED): The credit of ₹2,00,000 on 2026-10-20 (bank_txn:1, ref 629312345678) is an advance payment from customer Ravi Traders (Ravi K, ravi.k@okaxis, party ID 2). It corresponds to the harvest weighment slip sent by ravi@ravitraders.example on the morning of 2026-10-20 for pond 2 at Godavari Aqua Farm (4,500 kg at Rs.270/kg, gross value Rs.12,15,000.00), for which Ravi K transferred ₹2,00,000 via UPI shortly after.
- cited: ravi@ravitraders.example: Weighment slip, harvest 20 Oct - Godavari Aqua Farm; alerts@hdfcbank.example: Credit alert: Rs.2,00,000.00 credited to your account ending 7310

## 4. Move 3, Wed 21 Oct 12:00: the ₹6,46,800 settlement with new bank details; the owner confirms the bill, rejects the details, and asks Ravi Traders to pay early: FAIL

vendor + owner, read at Wed 21 Oct 12:00

**Error:** the page marks due_date on entry 2, and the step gives the owner no value for it

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `details-held` | change_pending | change_pending | PASS | fixture 04's account 8876 differs from 2201 on record: code holds the old details and asks |

## 5. Move 4, Thu 22 Oct 10:00: the lease asked early; the caretaker's Telugu voice note (₹3,000 diesel) and a photo of Venkat Motors' ₹18,000 repair slip; the owner confirms both bills and approves Thursday's payments: FAIL

landowner + helper + owner, read at Thu 22 Oct 10:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `lease-not-paid-early` | ('2026-10-31', False) | ('2026-10-31', False) | PASS | the landowner's email changes no bill: the lease stays due Sat 31 Oct |
| `two-bills-not-one` | ['passed', 'passed'] | ['passed', 'passed'] | PASS | the delta: a ₹3,000 diesel bill and an ₹18,000 repair are two bills, so neither is a duplicate |
| `transcript-beside-it` | True | True | PASS | the voice entry shows what was said beside the bill |
| `voice-bill` | ('RAJU PETROL BUNK', None) | ('RAJU PETROL BUNK', None) | PASS | the delta: 'Raju petrol bunk diesel bill ... three thousand rupees, twenty-fourth October 2026'; found by its ₹3,000 and 24 Oct, the vendor compared as the app compares names |
| `slip-bill` | ('VENKAT MOTORS', 'VM412') | ('VENKAT MOTORS AERATOR PUMP REPAIRS BHIMAVARAM', 'VM412') | **FAIL** | the delta's slip: VM/412, Rs. 14,000 + Rs. 4,000 = Rs. 18,000, pay by 25/10/2026 |
| `new-bills-in-the-plan` | (('PAY 2026-10-22', True), ('PAY 2026-10-22', True)) | (('PAY 2026-10-22', True), ('PAY 2026-10-22', True)) | PASS | the planner's own decision and reason (PO): both fall due before the next payment day, Mon 26, so each is paid today, Thu 22, its 'latest payment day on or before the due date'; the shortfall is the dealer's ₹6,46,800 (ESCALATE), not these |
| `thursday-approved` | ('PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED') | ('PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED', 'PAYMENT_EXPECTED') | PASS | the owner approves the plan's four PAY lines for Thu 22 (APSPDCL, the wages, the diesel and the repair, ₹51,000), so each is paid by its due date; the money moves only in his bank app |

- lease: PAY 2026-10-29
- transcript: Raju petrol bunk diesel bill generator kosam 3000 rupees 24th October 2026 lopala kattali
- plan: {'LEASE-OCT26': 'PAY 2026-10-29', 'APSPDCL-OCT26': 'PAY 2026-10-22', 'WAGES-OCT26': 'PAY 2026-10-22', 'SLAF/INV/0931': 'PAY 2026-10-26', 'Raju petrol bunk': 'PAY 2026-10-22', 'VM/412': 'PAY 2026-10-22'}

## 6. Move 5, Fri 23 Oct 16:00: Ravi Traders pays the balance ₹95,000 short; the owner links it to HARVEST-BAL and approves Monday's payments: FAIL

bank + agent + owner, read at Fri 23 Oct 16:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `payer-matches-amount-doesnt` | ambiguous_match | ambiguous_match | PASS | RAVI TRADERS names Ravi Traders, but ₹9,20,000 is no open invoice's amount |
| `agent-finding-shown` | True | True | PASS | PO: the explain_credit card shows what the agent found for its case, labelled as its words |
| `nothing-preselected` | False | False | PASS | PO: the AI informs and the owner decides: no invoice is chosen for him |
| `checklist-5-balance-confirmed` | ('CONFIRMED', 2) | ('CONFIRMED', 2) | PASS | handoff checklist 5: HARVEST-BAL is CONFIRMED with the ₹9,20,000 credit |
| `checklist-5-gap-named` | True | True | PASS | handoff checklist 5: the event names the gap: 10,15,000 - 9,20,000 = 95,000 |
| `checklist-5-floor-holds` | (True, True) | (True, True) | PASS | handoff checklist 5: the plan's lowest balance is at or above the ₹50,000 safety amount |
| `dealer-approved` | PAYMENT_EXPECTED | None | **FAIL** | the owner approves Monday's payments, the dealer's settlement among them |

- agent (RESOLVED): Bank transaction bank_txn:2 (credit of ₹9,20,000 on 2026-10-23, reference N296271234567 from RAVI TRADERS) settles receivable 2 (invoice HARVEST-BAL, ₹10,15,000). Payment advice 06-payment-advice-ravi-traders.eml confirms settlement for the harvest balance (Rs.12,15,000.00 less advance Rs.2,00,000.00 = Rs.10,15,000.00). Bank credit alert 07-credit-ravi-traders-neft.eml confirms the NEFT credit of Rs.9,20,000.00 with reference N296271234567 arrived immediately after, settling receivable 2 as a part payment.
- cited: ravi@ravitraders.example: Payment advice - harvest balance, Godavari Aqua Farm; alerts@hdfcbank.example: Credit alert: Rs.9,20,000.00 credited to your account ending 7310
- event: Owner: this ₹9,20,000 credit settles Ravi Traders HARVEST-BAL, short by ₹95,000 (₹10,15,000 invoiced).
- plan: lowest ₹10,79,000 on 2026-10-29; {'LEASE-OCT26': 'PAY 2026-10-29', 'SLAF/INV/0931': 'PAY 2026-10-26'}

## 7. Move 6, Mon 26 Oct 11:00: the dealer's NEFT lands; the bill is paid: FAIL

bank, read at Mon 26 Oct 11:00

| Check | Expected | Actual | Result | Why |
| --- | --- | --- | --- | --- |
| `dealer-paid` | PAID | None | **FAIL** | fixture 08's ₹6,46,800 NEFT to SRI LAKSHMI AQUA FEEDS matches the approved bill |
| `balance` | 58320000 | 58320000 | PASS | 12,30,000 - 6,46,800; the alert shows Rs.5,83,200.00 |
