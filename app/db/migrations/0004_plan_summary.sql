-- Batch 6 plan, CHG-018 (explain_plan). The plain-text "what changed" summary
-- of a plan run against the run before it, and where its words came from:
-- 'gemini' (every amount and date checked against the diff) or 'template'
-- (built by code from the diff). NULL until explain_plan runs, and for a run
-- that changed nothing.
ALTER TABLE plan_run ADD COLUMN summary_text TEXT;
ALTER TABLE plan_run ADD COLUMN summary_source TEXT CHECK (summary_source IN ('gemini', 'template'));
