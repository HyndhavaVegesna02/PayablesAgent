# Batch 11: plan (the PO's batch 10 verdict)

**Branch:** `batch-11`, cut from main at 43c8938. Both changes are direct lane: each is in one or two modules
and shows in one command. Their acceptance criteria are in docs/changes/CHG-037 and CHG-038.

- **CHG-037.** The voice amount check compares numbers, not text. `app/domain/money.py::amounts_said` reads
  every amount in the transcript, each in full (the longest run of words the spoken-amount parser reads).
  The check passes only when the paise parsed from amount_spoken equals one of them; otherwise, or when the
  transcript has no amount the parser reads, the bill goes to the owner with the amount empty.
- **CHG-038.** The ablation report's comparison paragraph says every harness's owner types the same values
  from the scenario. The fixture ablation report is regenerated, the old one kept as superseded.

No live calls in this batch.
