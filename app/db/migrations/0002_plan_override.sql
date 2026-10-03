-- Batch 4 plan, CHG-021; PO decisions D17 (this table) and D18 (a bounded
-- authorisation). An owner's choice the planner must honour: written only
-- through app.ledger.writer (record_override, end_override), each move an event.
CREATE TABLE plan_override (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  payable_id INTEGER NOT NULL REFERENCES payable(id),
  kind TEXT NOT NULL CHECK (kind IN ('authorise_breach','delay_flexible')),
  shortfall_option_id INTEGER REFERENCES shortfall_option(id),
  floor_paise INTEGER,                  -- authorise_breach: the lowest balance the owner saw (D18)
  breach_on TEXT,                       -- authorise_breach: the day that lowest was shown on
  created_by INTEGER NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ACTIVE','ENDED','LAPSED')),
  ended_at TEXT,
  CHECK (kind <> 'authorise_breach' OR floor_paise IS NOT NULL)
);
