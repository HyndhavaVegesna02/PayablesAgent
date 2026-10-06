# The AFTER: the pilot's two failures, rerun live after batch 8

The PO authorised one live run of scenarios 04 and 07, with traces kept, once batch 8's fixes were in:
CHG-030 for scenario 04 and CHG-031 for scenario 07. The BEFORE is `../live-pilot-before/`, with its
trace rerun in `../live-pilot-before/traces/`. This report's header names its commit, prompt version
and cost.

The traces were checked before commit. None of these appears in them:
- the value of any configured secret;
- a Google API key pattern;
- an unredacted password, token, key or secret field.

What the traces show:
- `04-hinglish-voice-note-run1/`: the model again gave no due date for a date said without a year. The
  entry now waits for the owner with the field marked, and the scripted owner fills it in.
- `07-missed-alert-causes-drift-run1/`, job 11:
  - the agent's first search used Gmail's `from:` operator, which the folder mail source didn't
    understand, so nothing matched (fixed after this run in batch 8; see the batch's review);
  - it searched again by the account's last digits, found the missed alert, proposed it with the
    schema's fields, and resolved the case at medium thinking;
  - the debit's source names the case.
