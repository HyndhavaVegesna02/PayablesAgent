-- Batch 6 plan, CHG-008 (the exception agent).
-- agent_case.state_json: the machine half of a case, the part the case file is
-- rendered from (message IDs seen in this case's searches, candidates and their
-- checks, findings, notes, the last tool call), so a run resumes at its step.
ALTER TABLE agent_case ADD COLUMN state_json TEXT NOT NULL DEFAULT '{}';

-- Q1: the agent's ask_owner question. SQLite cannot alter a CHECK, so the table
-- is rebuilt with the one new kind; rows and ids are kept.
CREATE TABLE owner_question_new (
  id INTEGER PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES business(id),
  case_id INTEGER REFERENCES agent_case(id),
  kind TEXT NOT NULL CHECK (kind IN
    ('confirm_record','unlock_pdf','explain_txn','confirm_balance','choose_option',
     'approve_bank_change','reconnect_gmail','ca_reminder','agent_question')),
  body_text TEXT NOT NULL,              -- shown as plain text
  choices_json TEXT,
  answer_json TEXT,
  answered_by INTEGER REFERENCES app_user(id),
  answered_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('OPEN','ANSWERED','EXPIRED'))
);
INSERT INTO owner_question_new SELECT id, business_id, case_id, kind, body_text, choices_json, answer_json,
  answered_by, answered_at, status FROM owner_question;
DROP TABLE owner_question;
ALTER TABLE owner_question_new RENAME TO owner_question;
