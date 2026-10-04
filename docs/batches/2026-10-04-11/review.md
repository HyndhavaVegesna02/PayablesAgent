# Batch 11 review

## Round 1: FIX_REQUIRED

Reviewed 43c8938..d4dd0b3. CHG-038 met both criteria. CHG-037 did not meet AC1 and AC3.

**Critical.** When the parser refused a longer run on purpose ("ek lakh pachaas" is ambiguous; "five hundred
thousand" has a scale with no number before it), amounts_said fell back to the leading part. "ek lakh" then
passed for "ek lakh pachaas", and "five hundred" for "five hundred thousand rupees". That is the bug class
CHG-037 was meant to remove, reached through the parser's refusals instead of a substring.

**Major.** "Equals one of the transcript's amounts" lets the model choose among the transcript's numbers: a
date ("5"), an invoice number ("418"), an advance, a correction ("2 lakh nahi"), or GST. The old substring
check allowed the same; this is not a regression. The reviewer asked for a PO ruling.

**PO D29** (ruling on the major): only money-shaped amounts count; more than one distinct money-shaped amount
flags the bill (the same amount said twice is one); the bill passes only on exact equality with that single
amount. Extra false flags are the right trade.

Minors:
- stale prose in app/validate/README.md and evals/knockouts.py;
- an `in ([], [41_800])` assertion that allowed either value;
- the prepatch note cited only the import error;
- a trailing blank line in money.py.

The reviewer judged design (b) (replacing the batch 5 words rule with equal paise) consistent with the PO's
instruction, with no coverage lost.

**Fixes:**
- `money_said` replaces amounts_said. A refused run that goes on with more of a number is None (unreadable),
  never its leading part; only money-shaped amounts count (D29).
- The check passes only when the distinct amounts said are exactly the one parsed from amount_spoken. The
  failure says why: unreadable, none, more than one, or a different one.
- Every reviewer input is a table test in both forms (money_said and check_voice), with the exact expected
  list, plus the same amount said twice (passes).
- The two known false flags (no unit or full stop before the next number word) are tests too.
- The stale prose, the prepatch note and the blank line are fixed.

## Round 2: FIX_REQUIRED

Re-review of 65b82ef and c3fa72d. The round-1 minors were resolved and D29 was recorded accurately.

**Critical.** The same class as round 1's critical, reached another way: money_said treated only the
parser's own vocabulary as part of a number. A number word the parser doesn't read acted as a boundary, so
the readable fragment beside it passed as the whole amount:
- "ek lakh dus hazaar" and "ek lakh baees hazaar" passed as "ek lakh" (Hindi 21-99 and "dus" are missing
  from the parser);
- "sava do lakh" passed as "do lakh", "ek laakh pachaas hazaar" as "pachaas hazaar", "minus pachaas hazaar"
  as "pachaas hazaar", and "a hundred and fifty thousand" as "fifty thousand";
- "Teen sau bori aayi, baees hazaar ka bill" left the count, ₹300, as the one amount;
- a tail after the unit or a full stop was dropped ("ek lakh rupaye pachaas", "Bill ek lakh. Pachaas.").

Minor: "ek lakh rupaye pachaas paise" dropped the paise.

**Fixes:**
- money_said reads clusters whole, never greedily. A cluster is a run of number words, with connectors,
  commas and an Rs or rupee word before it inside. It is read whole by parse_spoken_inr or, if money-shaped,
  is None.
- A list of number words the parser doesn't read is used for membership only, never for a value. A gap in
  it can't create a wrong amount through it, and an extra word can only flag. It covers Hindi 11-99
  spellings, sava, saare, laakh, minus, paise and others; hyphenated numbers count as number words.
- After a rupee word or a sentence end that closed an amount, a number word (with only connectors between)
  makes that amount None. A comma after a rupee word is a clean end, so "dedh lakh rupaye, paanch November"
  still passes.
- Every round-2 input is a table row with its exact money_said list. New pass rows: "Rupees ... only", digits
  inside spoken words ("do lakh 21 hazaar"), and "dus din" after the amount. New known false flag: a number
  word right after a full stop ("pachaas hazaar. Paanch November tak.").

**Left for the PO** (the reviewer asked for an explicit acceptance):
- a spelling that is in neither list, next to a readable part, still passes that part;
- a single amount that isn't the bill's total, by meaning not by form ("baaki dedh lakh", "dono dedh lakh
  ke"), passes. Code can't tell what the words mean; the owner confirms every voice bill with the transcript
  beside it.

## Round 3: FIX_REQUIRED

Re-review of 728046a and 5e4eead. All round-2 rows read as asserted. Round 2's critical class remains, now
reached through the tokenizer and the cluster rules. These are not the spelling residue:
- **(A)** An amount written as one token with marks ("Rs. 1,50,000/-", "Rs1,50,000", "1,50,000rs", "1.5L",
  "150k", "2cr") was an ordinary word and was dropped, so an advance in the same note passed as the one amount.
  Short scales written as their own word ("Rs 50 k", "Rs 2.5 cr") let the digits before them pass.
- **(B)** "After digits only a scale goes on" closed the digits' cluster cleanly, so "Rs 1,00,000 pachaas"
  passed ₹1,00,000. "25 - 30 lakh" passed as its upper bound.
- **(C)** A hyphenated amount ("dedh-lakh") was number-like but never money-shaped, so a count became the
  one amount ("Teen sau bori, dedh-lakh ka bill"). A literal underscore glued words.

Minor (meaning, for the PO): a word between an amount and a tail; ranges and guesses ("25 to 30 lakh",
"lagbhag do lakh", "do lakh se zyada", "ek lakh plus GST").

All of round 3's findings are instances of the defect round 1 named (a part of what was said passes, or the
real amount is dropped). By the loop's rule, this round does not count toward the cap of three.

**Fixes:**
- A written amount token (digits with Rs, INR or ₹ before; "/-" or "-", a currency or a short scale after)
  is a number word, money-shaped when it carries a mark. The parser reads it whole, or it is None.
- A short scale straight after digits joins the amount and makes it None.
- A number straight after digits, with no comma between, makes the digits' amount None. After a comma it
  starts its own ("Rs 1,50,000, 5 November").
- A hyphen or slash compound is number-like if any part is. It is money-shaped if any part is, so
  "dedh-lakh" reads ₹1,50,000 and "lakh-ish" is None.
- Paise is money-shaped. A literal underscore is a space.
- Ranges and guesses are now caught by form rather than left as residue. A dash between numbers, or a word
  for a range or guess after an amount (to, ya, or, se, zyada, kam, plus) or before one (lagbhag, kareeb,
  around, about, over, under), makes the amount None.
- Every round-3 input is a table row with its exact money_said list.

**Still left for the PO** (no form shows them):
- a word between an amount and a tail ("Bill ek lakh hai, pachaas"; "ek lakh rupaye, pachaas");
- an amount that isn't the total by meaning ("baaki dedh lakh");
- a spelling in neither list.
These are tested as they behave.

## Round 4: FIX_REQUIRED

Re-review of 073bc69 and 9387481. Every round-3 row reads as asserted. Round 3's class (A) was still open:
written amounts were matched by an allow-list (_WRITTEN_AMOUNT), so a form outside it was an ordinary word and
was dropped, and an advance passed as the one amount. Examples: "1,50,000rupaye", "1,50,000/=",
"50hazaar", "1,50,000x2", "-1,50,000". This is the same defect again, so the round does not count toward the
cap.

Minors:
- a guess after a rupee word or a full stop had closed the amount ("do lakh rupaye se zyada", "ek lakh. Plus
  GST."), and "+" ("ek lakh + GST"), passed;
- the parser's sign check missed "₹-1,50,000";
- "do lakh, 50,000 advance" merged into one amount;
- false flags: "paise" meaning money in general, a dotted date, "de-do".

The reviewer judged that the work has reached diminishing returns. After this structural fix, what remains
depends on meaning, and if the next round finds only that, it should approve.

**Fixes:**
- By form, not by list: any word with a digit in it is a number word. It is money-shaped when it has a comma
  grouping, ₹, a mark after the digits ("/-", "/=", "/", "-", "="), or letters on the digits that make them
  money (Rs, INR, k, L, lakh, cr, hazaar, a rupee word...). An invoice number, an ordinal or a date stays bare.
  The parser reads the word whole, or it is None.
- A mark is a token with no letter or digit, so "-1,50,000" is an amount, and the parser refuses it as
  negative.
- After a closed amount, a guess word (se, zyada, kam, plus, upar, approx; not "to", which is "so" there) or
  "+" makes it None. Inside an amount, "+" is a range mark like a dash.
- parse_spoken_inr checks the sign after a leading ₹, Rs or INR.
- A comma-grouped written amount after a comma starts its own amount.
- "paise" counts only after a number. A compound is a number word only if all its parts are, or one is a
  scale ("lakh-ish" yes, "de-do" no).
- Every round-4 input is a table row. Pass rows cover the removed false flags and "rupaye to dena hai".

**Left for the PO**, as before (no form shows them): a word between an amount and a tail; an amount that
isn't the total by meaning; a spelling in neither list; a guess word not in the lists ("ke aas paas").

## Round 5: APPROVE

Re-review of ab570e6 and 000258b. Every round-4 critical input now flags. New written forms the reviewer
probed flag too: "1,50,000rup", "1.5lakh", "150thousand", "Rs -1,50,000", "Rs 1,00,000 50k". No structural
path is left that drops a money-shaped amount the parser reads. Full suite 1461 passed, 9 import contracts
kept, ruff clean, check_evidence: all 5 reports reproduce.

Minors, put in the backlog as CHG-039 (draft) for the PO to order:
- a Unicode minus ("−1,50,000") is split off as a mark, so the digits read as positive;
- parse_spoken_inr("rupees -5") is 500: the sign check strips ₹, Rs and INR but not a rupee word;
- range punctuation the dash rule doesn't cover ("25 / 30 lakh", "25 -- 30 lakh", "25 & 30 lakh") passes the
  upper bound.

For the PO (D29 rule 1, not a code defect): ungrouped digits ("150000") are not money-shaped, so a note that
writes the bill bare and an advance grouped passes the advance. Counting a bare run of five or more digits as
money would close it, at the cost of false flags on long invoice numbers.

**Residue for the PO's acceptance** (by meaning, not form; each passes the head amount):
1. a tail after an ordinary word or a comma ("Bill ek lakh hai, pachaas"; "ek lakh rupaye, pachaas");
2. an amount that isn't the total by meaning ("baaki dedh lakh"; "dono dedh lakh ke");
3. spellings in neither word list;
4. guesses and ranges in words not on the lists ("ke aas paas", "ya usse zyada", "rupees to 2");
5. a comma merge only the model could share ("do lakh, 50 hazaar advance" reads ₹2,50,000);
6. the bare-digits point above.

Every voice bill is still confirmed by the owner with the transcript beside it.

