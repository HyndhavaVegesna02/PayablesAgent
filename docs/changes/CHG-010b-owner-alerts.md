---
id: CHG-010b
title: Owner alerts by email
type: feature
lane: planned
---

## Context
Split from CHG-010 (Evidence) in the batch 7 plan, docs/batches/2026-10-03-7/plan.md (PO approved, D22-D25). CHG-009 keeps only the Gmail half.

## Description
notify/smtp.py, templates and the send_alert job. Fixed templates; the recipient comes from the database only; the alerts.min_minutes_between_emails throttle as a digest; a separate SMTP account via env; an in-process fake SMTP in tests; ai and agent never import notify.

## Acceptance Criteria
See the batch 7 plan's "CHG-010b" section: its requirements table is the acceptance list, as the PO approved it.

## Expected paths
See .yourteam/backlog.yaml.

## History
- 2026-10-03: split from CHG-010; planned and approved for batch 7
