# Demo script: the shrimp farm's harvest fortnight

Dev only (R011, extended by the PO for the shrimp profile: nothing here goes to the public tree
without the PO's explicit go). About 12 minutes with talk. CHG-058.

Godavari Aqua Farm is a vannamei shrimp farmer in coastal Andhra Pradesh. The farm, its people, its
bank and every figure are fictional. The fortnight is weeks 15 to 16 of a 110-day crop: the final
harvest and the settlement. Four counterparties matter: the feed dealer (Sri Lakshmi Aqua Feeds), the
commission agent who sells the harvest (Ravi Traders), the landowner (K. Subba Rao) and the
electricity board (APSPDCL). The caretaker, Lakshman, is paid wages.

The quotes below are what the pages render in the offline rehearsal (`make rehearse-shrimp`).
Live, Gemini's own words differ: the assistant's findings, the sort of each email, and the voice
note's transcript. The figures, the plan and every state change are code's: the same whenever the
documents are read right, and marked for the farmer when they aren't.

## What must be in place

- **`.env`** (the user's, never read or edited by the build): `GEMINI_API_KEY` for live runs;
  `SESSION_SECRET`, without which the web app refuses to start; and `FERNET_KEY`, without which mail
  and uploads can't be stored. If `make run-shrimp` says `SESSION_SECRET is not set`, or the worker
  names `FERNET_KEY`, the message names the command that makes the value. Add the lines to `.env`
  yourself.
- **The real uploads** (see "Files to supply" below). Until they are in place the placeholders are
  used, and only offline.
- **Billing headroom** on the Gemini project, checked the day before and the morning of. Google's
  monthly spending cap stopped a live run on 4 Oct.

## Before the panel

```
make reseed-shrimp          # ./data/shrimp.db only; refuses any other database
make run-shrimp             # the web app, http://localhost:8000
make worker-shrimp          # the worker: live Gemini (DEMO_AI blank in .env.shrimp)
```

Log in as `owner@example.test` / `owner-demo-pass`. Second window: the worker terminal. Third: the
trace viewer, `uv run python scripts/with_env.py .env.shrimp -- python -m app.trace.view <run_id>`
(the run ID is in the worker log).

`.env.shrimp` is applied as process environment by every `*-shrimp` target, so it overrides `.env` for
those commands only: config.shrimp.yaml (the profile's mail senders), fixtures/shrimp_inbox,
./data/shrimp.db, ./data/shrimp-files, ./traces/shrimp, the demo clock at Mon 19 Oct 09:00, and no
SMTP host (owner alerts wait unsent). The worked example's database and settings are untouched.

**If Gemini fails on stage** (a 429, a spend cap): stop the worker and start
`make worker-shrimp FALLBACK=1`. It answers from fixtures/shrimp_ai_replies.json, never Gemini, and
the page says "AI replies are canned fixtures."

**Reset between rehearsals:** stop both processes; delete `./data/shrimp-files` and
`./traces/shrimp`; `make reseed-shrimp`.

## The moves

Move the clock with `make demo-time-shrimp T=...` (or the "Move the clock" form on Settings). Each
move polls the mail at once; the worker reads what arrived.

### Start: Mon 19 Oct 09:00

**Say:** the crop story. 110 days, feed on credit from the dealer, the harvest this week, and
everything falls due at once.

**Show:** This week. "Covered for 14 days. You stay above your safety amount for the next 14 days.
Lowest: ₹1,10,000 on Mon 19 Oct." Safety amount ₹50,000. Ravi Traders' ₹2,00,000 advance is
expected in on Tue 20 Oct; the ₹10,15,000 balance isn't counted until it lands or the farmer asks
for it early.

### Move 1: `make demo-time-shrimp T=2026-10-19T12:00:00+05:30`

**Say:** "The last feed delivery. Gemini reads the invoice; code checks it; I confirm."

**Show:** Needs attention: bill entry from the email "Invoice SLAF/INV/0931 - 10 bags grower feed
delivered today": Sri Lakshmi Aqua Feeds, ₹25,000, with "Bank details on this bill: account ending
2201, IFSC SBIN0004321", the ones on record, so nothing is asked. Confirm. It is planned for Mon 26
Oct.

### Move 2: `make demo-time-shrimp T=2026-10-20T10:00:00+05:30`

**Say:** "Harvest day. Ravi pays the advance from his personal UPI. The bank says RAVI K; our books
say Ravi Traders. Watch the agent."

**Show:** the worker log (a case opens, `search_gmail`), then the trace viewer. Needs attention:

> A ₹2,00,000 credit on Tue 20 Oct from RAVI K (ravi.k@okaxis) (reference 629312345678) was not
> matched to an invoice. Which invoice did it pay, if any?

Under it, **The assistant found** (offline wording): "The ₹2,00,000 UPI credit from RAVI K
(ravi.k@okaxis) on Tue 20 Oct is Ravi Traders' harvest advance: their weighment slip, emailed at
09:00 that day, says 'Advance Rs.2,00,000 paid today by UPI from ravi.k@okaxis'. It looks like
HARVEST-ADV; please link it." It cites the message it found: "ravi@ravitraders.example: Weighment
slip, harvest 20 Oct - Godavari Aqua Farm". Then: "The assistant's words. They change nothing: only
the invoice you choose does."

Nothing is pre-selected. The farmer picks **Ravi Traders HARVEST-ADV ₹2,00,000 (counted in the plan,
expected on Tue 20 Oct)**, ticks "Also treat "RAVI K (ravi.k@okaxis)" as this customer's name in
future alerts", and presses **This paid the chosen invoice**. Code matches the credit and confirms
the invoice as the owner; the balance is ₹3,10,000, as the bank's alert says.

### Move 3: `make demo-time-shrimp T=2026-10-21T12:00:00+05:30`

**Say:** "The dealer's settlement invoice, six and a half lakh, and a new bank account. Code holds
the old details."

**Show:** Needs attention, two things:

> A bill from Sri Lakshmi Aqua Feeds gives different bank details: account ending 8876, IFSC
> ICIC0007788 (on record: account ending 2201, IFSC SBIN0004321). … Call the vendor on a number you
> already have before approving. Changed bank details are a common fraud.

and the bill entry from "Invoice SLAF/INV/1042 - season settlement, please pay within 5 days": Sri
Lakshmi Aqua Feeds, ₹6,46,800. Confirm the bill. The farmer called the dealer: the old account stands,
so **Reject: keep the old details**.

The plan flips. This week: "Below your safety amount. ₹5,16,800 below your safety amount on Thu 29
Oct. Lowest balance -₹4,66,800 on Thu 29 Oct", and "Sri Lakshmi Aqua Feeds needs your decision.
Pick how to cover the gap." The shortfall options:

| Option | Lowest balance | |
| --- | --- | --- |
| Ask Ravi Traders to pay ₹10,15,000 by Wed 21 Oct | ₹5,48,200 | Meets the safety amount |
| Split Sri Lakshmi Aqua Feeds: ₹2,05,000 now, ₹4,41,800 due Wed 4 Nov | -₹4,66,800 | Does not meet it |
| Authorise going below the safety amount (₹5,16,800 below on Thu 29 Oct) | -₹4,66,800 | Does not meet it |

Choose **Ask Ravi Traders to pay ₹10,15,000 by Wed 21 Oct**. The planner asks by the weekday before
the last payment day ahead of the breach (Thu 22 Oct, before Mon 26), which is today. Asking changes
no ledger row: the money counts when it lands, and the page shows "Asked by Wed 21 Oct; not
received".

### Move 4: `make demo-time-shrimp T=2026-10-22T10:00:00+05:30`, then the uploads

**Say:** "The landowner wants the lease early. Harvest week means the generator runs: the caretaker
sends a Telugu voice note about the diesel bill and a photo of the aerator repair slip."

**Show:** the landowner's email ("Please send the lease instalment this week if possible") is not a
bill, so nothing changes: the lease, ₹75,000, stays due Sat 31 Oct and planned for Thu 29 Oct.
Paying it now would deepen the gap the dealer's bill opened.

Log in as the helper (`helper@example.test` / `helper-demo-pass`) and upload, on Add, the voice note
and then the photo of the repair slip. They are two different bills, so neither is flagged as a
duplicate. As the owner, Needs attention shows both:

- the voice note, with "Transcribed by the assistant", "What was said:" and the transcript beside it,
  and "Please check this bill from an uploaded voice note: Raju Petrol Bunk, ₹3,000." The Telugu note
  says the amount and the date in English ("three thousand rupees, twenty-fourth October 2026"),
  because code reads the amount from the words said, never the model's figure, and it reads no Telugu
  number words yet. Offline, the placeholder's canned transcript is "Raju petrol bunk diesel bill,
  generator kosam, three thousand rupees, twenty-fourth October 2026 lopala kattali.";
- the photo: "Please check this bill from an uploaded photo: Venkat Motors, ₹18,000." That is slip
  VM/412, ₹14,000 rewinding plus ₹4,000 bearings and gearbox oil, pay by 25 Oct.

Confirm both. Every check passed, so nothing is marked and nothing needs typing. The planner pays both
today, Thu 22 Oct, the last payment day before they fall due (Sat 24 and Sun 25): "You're approving
4 payments, ₹51,000", with APSPDCL and Lakshman's wages. The plan is still below the safety amount
("Lowest balance -₹4,87,800 on Thu 29 Oct"): the gap is the dealer's ₹6,46,800, not these. The floor
is restored at move 5, when the harvest balance lands.

### Move 5: `make demo-time-shrimp T=2026-10-23T16:00:00+05:30`

**Say:** "The processor pays, ninety-five thousand short. The payer matches; the amount doesn't. The
agent reconciles it against the advice."

**Show:** Needs attention:

> A ₹9,20,000 credit on Fri 23 Oct from RAVI TRADERS (reference N296271234567) was not matched to an
> invoice. Which invoice did it pay, if any?

**The assistant found** (offline wording): "The ₹9,20,000 NEFT from RAVI TRADERS on Fri 23 Oct is the
harvest balance, paid short: Ravi Traders' payment advice, emailed at 15:00, takes ₹10,15,000 less
re-grading ₹22,500, soft shell ₹24,300, ice and crew ₹20,000 and commission ₹28,200 (₹95,000 in all)
and pays ₹9,20,000. It looks like HARVEST-BAL, short by ₹95,000; please link it." It cites "Payment
advice - harvest balance, Godavari Aqua Farm".

The one invoice offered: **Ravi Traders HARVEST-BAL ₹10,15,000 (not counted in the plan, expected on
Fri 30 Oct; short by ₹95,000)**. Choose it and press **This paid the chosen invoice**. The event says, in
code's words: "Owner: this ₹9,20,000 credit settles Ravi Traders HARVEST-BAL, short by ₹95,000
(₹10,15,000 invoiced)." The invoice's amount is never edited; the event is the record.

The plan is redone: "Covered for 14 days. Lowest: ₹4,32,200 on Thu 29 Oct." Approve Monday's
payments: the dealer's ₹6,46,800 and ₹25,000, APSPDCL ₹15,000, Lakshman's wages ₹15,000, Raju Petrol
Bunk's ₹3,000 and Venkat Motors' ₹18,000. Thursday's four weren't approved on Thursday, so the plan
now pays them on Monday, late: APSPDCL was due Thu 22, the wages Fri 23, the diesel Sat 24 and the repair
Sun 25. To pay them on time, approve Thursday's payments at move 4 instead. "You pay them in your bank
app; we never move money."

### Move 6 (optional): `make demo-time-shrimp T=2026-10-26T11:00:00+05:30`

**Say:** "The dealer's NEFT lands, to the account on record, and the bill is paid."

**Show:** the ₹6,46,800 NEFT to SRI LAKSHMI AQUA FEEDS matches the approved bill: PAID. The plan is
"starting from ₹5,83,200 in your bank accounts", the bank's own figure. "Lowest: ₹4,32,200 on Thu 29 Oct." The other approved
payments wait for their bank alerts.

## If something reads differently live

- A wrong extraction goes to Needs attention with the field marked: correct it by hand and say "the
  model reads, the farmer confirms."
- An agent that takes another path is fine if the ending is right: narrate the trace it took. If it
  ends NEEDS_OWNER, its question appears too, and linking the credit answers both.
- If the move-5 payer is read as something other than "RAVI TRADERS", the case is unknown_txn instead
  of ambiguous_match, and the question offers every open invoice. Choose HARVEST-BAL all the same.
- The voice note's amount: code reads English, Hindi and Hinglish number words, not Telugu ones, so
  the note says "three thousand rupees" in English. If the amount is marked "type it in", read the
  transcript to see what Gemini wrote for the number words before changing anything, then type ₹3,000
  and say "the model hears, code checks, the farmer confirms."

## Files to supply

Drop them in `fixtures/shrimp_uploads/`; the rehearsal driver picks them up by name. Until a canned
reply is added for each, the offline fallback keeps using the placeholders (D7).

| File | What | Formats the app takes | Limit |
| --- | --- | --- | --- |
| `voice-diesel-raju.wav` | a real recording by a Telugu speaker, about 6 seconds, phone held close, no background noise, exactly one amount: "Raju petrol bunk diesel bill, generator kosam, three thousand rupees, twenty-fourth October 2026 lopala kattali." (రాజు పెట్రోల్ బంక్ డీజిల్ బిల్, జనరేటర్ కోసం, three thousand rupees, twenty-fourth October 2026 లోపల కట్టాలి.) | .wav as named; .ogg or .opus (a WhatsApp voice note as is), .mp3 or .m4a also read | 10 MB |
| `repair-slip-venkat.jpg` | a real photo of a handwritten slip on a cash-memo pad, blue ballpoint, daylight, slightly angled: VENKAT MOTORS, Aerator & Pump Repairs, Bhimavaram; Bill No: VM/412; Date: 22/10/2026; To: Godavari Aqua Farm; 1. Aerator motor rewinding (2 nos) Rs. 14,000; 2. Bearings & gearbox oil (2 sets) Rs. 4,000; Total Rs. 18,000; Pay by 25/10/2026; signed Venkat. No GST line. | .jpg as named, or .png (an iPhone's HEIC must be exported as JPEG) | 10 MB |

The Add page takes the type the browser names, or the one the extension implies; the worker then
reads the type from the file's first bytes, so the extension has to be honest.

## Rehearsal

`make rehearse-shrimp` plays moves 1 to 6 offline through the real routes, the worker and the demo
clock, and checks each move's end state (the handoff's checklist items 4 and 5) and that the
assistant's finding is on each credit's card with nothing pre-selected. Live, only when the PO
authorises it: `make rehearse-shrimp ARGS="--ai live --yes-spend --max-usd 1.00"`, under the budget
guard. Each rehearsal writes its report, traces and database to `rehearsals/` (git-ignored).
