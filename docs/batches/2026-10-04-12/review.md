# Batch 12 review

One review round (PO, batch 11 verdict).

## Round 1: FIX_REQUIRED

Reviewed 2a889a2..1503adc. AC1, AC3, AC4 and AC5 were met; AC2 was partial. The reviewer compared old
against new on 177 inputs (every voice table input plus about 50 probes). It confirmed the prepatch note
exactly: 13 of the 19 new tests fail by assertion on the old tree, and 6 are guards.

**Critical, a regression the change introduced.** Mapping the Unicode minus to "-" made two flagged inputs
pass with a wrong amount:
- "Bill do lakh −50,000 advance": parse_spoken_inr dropped a mid-text "-", so the minus read as a plus
  (₹2,50,000);
- "Bill do lakh− advance 50,000": "lakh-" was not a number word, so "do lakh" was dropped and the advance
  passed.
Their ASCII twins already passed at 2a889a2 (pre-existing holes).

Minors:
- D30's own trade: a bare 5+ digit invoice number that is the only amount-like thing passes if the model
  takes it as the amount; new false flags on pin codes, phone numbers and leading zeros;
- "/" and "&" after a number flag even with no number after (safe);
- a test name.

**Fix** (not re-reviewed; the PO allowed one round):
- parse_spoken_inr refuses a word starting with a minus after the first word, and a minus glued between a
  letter and a digit ("lakh-50");
- a number word with a mark after it ("lakh-") is still a number word, and money-shaped like the word;
- the four inputs and their ASCII twins are table rows; the test is renamed.
The reviewer's own old-against-new probe (scratchpad cmp.py), rerun on the fix over the same 177 inputs: the
only flag-to-pass changes left are the bare-digits passes D30 intends (a bill said as bare digits).
