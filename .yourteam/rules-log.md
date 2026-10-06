# Rules Log

Provenance for `rules.md`, keyed by rule ID. Read at audit time, not during
work. This file may grow; rules.md may not.

Each entry: what happened, when, what it cost, and what was considered and
rejected. When a rule is deleted, append the audit that deleted it rather than
removing its entry -- knowing why something was dropped is what stops it being
reinvented.

## R001
Human-stated conventions outrank observed patterns. Carried forward as a
default. Without it, an agent reading neighboring code will "helpfully" match a
pattern the human has explicitly moved away from.

## R002
Scope is frozen once a batch starts, and tooling is part of scope: a new dependency
with an install step changes the ground every remaining change is being measured on,
and it does so after the baseline was proven green. The carve-out matters as much as
the rule. Landing an already-approved rule at a mechanism that already exists — a gate
command, a script, a hook, an agent definition — is never blocked by the freeze,
because forcing a lesson down to the weakest available rung purely because of when it
was learned is worse than having no rule at all.

## R003
Bulk staging once swept an unrelated state edit into a change's commits, which
made the change's diff unreviewable and its cherry-pick unsafe. Separately, a
test runner's progress output broke a shell chain, `git checkout -b` silently
did not run, and an entire change was committed to the default branch. Both are
now hook-enforced; the prose survives only as the fallback where hooks can't run.

## R004
Replaces a model-read AC-to-test trace that cost a full dispatch per change.
The failure it catches: a test named for a guard that actually exercised an
already-passing path, which survived a name-matching review. Lineage worth
noting -- SWE-bench's own harness discards model edits to test files for the
same reason, and DG-Forge states the general form as: a result read before a
prediction is formed is observation, not verification.

## R005
A dispatch brief invited a reviewer to re-run a mutation; it did, then reverted
with `git checkout --`. A second reviewer was running concurrently on the same
tree, so for that window the isolation this rule asserts was simply absent. No
harm was detected and only the reviewer's own disclosure made it visible. The
lesson is not that the reviewer should have known better -- it is that a brief
silently outranked a rule, which is why the rule now sits in the agent
definition and says explicitly that a brief cannot lift it.

## R006
A change identified NULL handling as its risk area, wrote a plan section about it,
wrote a test that executed real SQL against a real engine — and still shipped a bug,
because it answered the null-*element* question and never asked the null-*array* one.
Nothing in the plan template, the gates or the router asked whether the enumeration was
complete. The contract table already existed and was filled in carefully: seven rows,
four verified by execution. Thoroughness was not the problem; invisible incompleteness
was. Hence a fixed grid rather than prose — a paragraph can be careful and silently
partial, a grid with a blank cell cannot. Empty and absent are separate cells because
conflating them is the recurring form of this bug.

## R007
The demo committed as a batch's evidence of record still showed pre-fix output after the
fix landed. Caught at review and correctly called blocking: an evidence file that
contradicts the code at its own commit is worse than no evidence file, because it is
read as proof. The loop had a demo step and no notion that a demo can go stale.

## Retired: the module-boundary trigger

The router once escalated any change spanning more than one module. Deleted after a
batch in which it fired on all three changes including a one-line one, because in a
layered codebase the layers *are* the decomposition axis, so crossing them is the
normal cost of doing anything. A signal that is on for every change is a constant, and
a constant carries no information. Replaying the router without it produced the same
routing that batch's retrospective concluded was correct, on all three changes — it
contributed no information and one wrong escalation. Raising the threshold to three
modules was considered and rejected: it would still have fired on two of the three.

## Candidate, not a rule: new vocabulary

Observed once, on one batch, and recorded here rather than promoted because one batch
of history justifies nothing. The changes that turned out cheap *bound an existing
concept* to more places; the one that turned out expensive *introduced a new name* the
rest of the codebase now has to know — a class, a public function, a config key, a
column. New vocabulary is what is costly to get wrong, because changing it later means
changing everything that learned it. If this distinction keeps predicting cost across
two or three more batches, propose it as a trigger with that falsifier.

## R008
Batch 1 (2026-10-02), PO decision D4. "Only the ledger writer writes ledger
tables" was prose in CLAUDE.md and the DoD. A static AST test now fails on any
SQL string outside writer.py that writes payable, receivable, bank_txn,
tax_obligation or event, or that UPDATEs/DELETEs bank_account (D10). At the start
commit it caught the old seed's raw INSERT/DELETE. Known limit: SQL with a runtime
table name is not caught. Approved by PO at batch 1 verdict.

## R009
Batch 0 review caught app/jobs/queue.py calling datetime.now() directly. The fix
added an AST guard test; batch 1 recorded it here as a rule at its rung. Approved
by PO at batch 1 verdict.

## R010
Batch 1: yt_prepatch.py runs `python -m pytest`, which resolved to a system
miniconda python without Hypothesis. A test could then "fail at the start
commit" with ModuleNotFoundError for hypothesis instead of for the missing
change, which makes the gate vacuous for it. Batch 1 ran prepatch under
`uv run` by hand. The fix is in the config the script already reads, so it is a
config rung, landed between batches 1 and 2 (R002). Approved by PO at batch 1
verdict.

## R011
2026-10-06, the user's explicit choice through the PO: docs/demo-script.md was erased from the public repo's
whole history (its three commits rebuilt without it, the README's two references removed, messages, authors and
dates kept), and docs/gmail-handover.md, never published, stays out. Dev keeps both files. Batch 19 built the
public tree by hand from a list (no .yourteam, .claude, docs/batches, docs/changes, docs/notes, docs/evals
superseded/ and invalid/, CLAUDE.md, the hackathon brief, the Gmail handover), and that list didn't name the
demo script, so a rebuild from it would have brought the file back. Prose rung: the public tree is assembled
outside any test this repo runs. Approved by the PO (user's direction).
