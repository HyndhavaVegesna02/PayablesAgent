# Batch 10: plan (PO D28 and the 11x5's two invocations)

**Branch:** `batch-10`, cut from main at 6f0e795. All four changes are direct lane: each is small, in one or two
modules, and shows in one command. Their acceptance criteria are in docs/changes/CHG-033 to CHG-036.

- **CHG-033 (D28.1).** `app/domain/money.py::without_currency_word` drops a trailing currency word, or a
  prefix of one of three letters or more. The spoken-amount parser and the voice check's said-words
  comparison use it. Anything else at the end is still refused.
- **CHG-034 (D28.2).** `attention.flagged_fields` marks every empty required field of a waiting bill or
  sales invoice. The scripted owner (runner `fill`; workflow run A's voice step) fills every marked field
  with the value the scenario states from the document or transcript. A marked field the scenario gives no
  value for is a scenario error.
- **CHG-035.** `evals/report.py` gains `combine`, which builds one md and json page from several
  report.json parts: the latest part wins per scenario, and every row names its source. `check-evidence`
  re-derives committed combined pages from their parts.
- **CHG-036.** docs/evals/README gets a section telling the live runs in order. Figures stay in the
  reports (D25).

No live calls in this batch. Part 2 (08-11, and 04 again, at N=5) waits for the PO's go.
