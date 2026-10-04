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
