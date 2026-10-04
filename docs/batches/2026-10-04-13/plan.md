# Batch 13: plan (the spend-cap 429)

**Branch:** `batch-13`, cut from main at 2382e41. One direct-lane change, CHG-040, in two modules, shown by
one command. The PO accepts directly on a green gate.

- `app/ai/client.py`: a 429 that names a spending cap or prepayment (in its message or an ErrorInfo reason)
  becomes a permanent AIUnavailable; other 429s stay retryable.
- `evals/budget.py`: a permanent 429 stops the invocation at once, with `stopped_because` naming the spend cap;
  no backoff.

No live calls.
