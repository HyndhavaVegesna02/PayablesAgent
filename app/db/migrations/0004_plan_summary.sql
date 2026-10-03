-- Batch 6 plan, CHG-018 (explain_plan). The plain-text "what changed" summary
-- of a plan run against the run before it, and where its words came from:
-- 'gemini' (every amount and date checked against the diff) or 'template'
-- (built by code from the diff). NULL until explain_plan runs, and for a run
-- that changed nothing.
ALTER TABLE plan_run ADD COLUMN summary_text TEXT;
ALTER TABLE plan_run ADD COLUMN summary_source TEXT CHECK (summary_source IN ('gemini', 'template'));

-- What each line pays: a PAY line that takes an early-payment discount pays
-- less than the bill. NULL on runs stored before this migration (read as the
-- bill's amount).
ALTER TABLE plan_line ADD COLUMN amount_paise INTEGER;
