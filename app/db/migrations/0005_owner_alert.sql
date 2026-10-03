-- Batch 7 plan, CHG-010b (owner alerts by email). Code raises an alert at the
-- TDD's four owner events; the send_alert job sends the unsent ones as one
-- fixed-template email per throttle window and stamps sent_at. The row holds a
-- kind and a record reference only: every figure in the email is read from the
-- ledger when it is sent, so nothing a document says reaches the email text.
CREATE TABLE owner_alert (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  kind TEXT NOT NULL CHECK (kind IN ('money_received','payment_failed','unexpected_debit','balance_mismatch')),
  ref TEXT NOT NULL,                    -- 'receivable:3', 'payable:5', 'agent_case:2', 'bank_txn:7', 'bank_account:1'
  created_at TEXT NOT NULL,
  sent_at TEXT,
  UNIQUE (business_id, kind, ref)
);
