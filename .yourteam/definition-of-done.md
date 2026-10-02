# Definition of Done

Every item holds before any change is done. `yt_gate.py` executes each command
literally and records command, exit code, output tail and commit SHA into
batch.yaml. Nonzero exit means not done.

## Commands
- [ ] Tests, Hypothesis properties and import-boundary checks pass: `make test` -> exit 0

## Standing rules
- [ ] Every acceptance criterion has at least one test driving it
- [ ] Gate results are recorded by the script, not by hand (`yt_gate.py --record CHG-NNN`)
- [ ] New tests fail at the change's start commit (`yt_prepatch.py --since <start>`)
- [ ] Knowledge notes this diff made stale are updated or flagged (`yt_stale.py`)
- [ ] If the change altered build/test/run commands, stack or architecture:
      CLAUDE.md updated in the same commit
- [ ] If the change deleted code: the reason is recorded in the change file
- [ ] Money is represented as integer paise everywhere — no float ever holds an amount
- [ ] Every ledger-table or payable/receivable/transaction state change goes through `ledger.writer.transition()` — nothing else updates a state column
