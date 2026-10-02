# Recovery

Read when something is off the happy path. Each entry exists because the obvious behavior corrupts state, blocks forever, or breaks an invariant quietly. They're grouped by when you hit them.

## Before a batch starts

**Red baseline.** A batch must start green. Run the gate commands on the default branch at plan time. Anything failing means the batch can't start — "restore green baseline" becomes its mandatory first change, or the human explicitly amends the Definition of Done. On an existing project whose suite is already red, don't write a DoD it can't meet: either fix the suite as batch 0 work, or scope the test gate to touched paths with a backlog entry to restore full coverage. Never quietly ignore failures; that teaches everyone red is normal.

**Dirty tree.** Require a clean tree before cutting the branch. A dirty tree contaminates commits and breaks the reversibility guarantee the whole loop rests on.

**No git repo.** Refuse to run. This loop without git has no undo, no blast radius and no recovery. `git init` and an initial commit first, with the human's confirmation.

**Default branch isn't `main`.** Detect once at setup — `git symbolic-ref refs/remotes/origin/HEAD`, or the current branch on a fresh clone — record it in `config.yaml` and CLAUDE.md, and use it everywhere. Hardcoding `main` breaks merge, rebase and recovery on `master` and `trunk` repos, silently.

**Cut the branch before writing state, and never chain a checkout with a commit.** The git guard reads `batch.yaml` for the branch name and blocks commits made from elsewhere; writing `branch:` first and then chaining `checkout && commit` trips it. Order: checkout and branch (no commit in the chain), write `batch.yaml`, then commit as a separate command from the new branch.

## During a batch

**Silent branch failure.** A failed `git checkout -b` doesn't stop a shell chain, so commits land on the default branch with no error surfacing. Verify `git branch --show-current` before every commit; the hook enforces it, and the prose is the fallback where hooks can't run. If it already happened: create the batch branch at current HEAD to preserve the work, hard-reset the default branch to its pre-batch commit, continue on the branch. This is not hypothetical — a test runner's progress output once broke a shell chain and an entire change went to `master`.

**The default branch moved.** Someone pushed while you worked. Before review: rebase the batch branch onto it, resolve conflicts, and **re-run the full gate** — a clean rebase can still break behavior. Refresh the evidence. A review against a stale base produces merges that break.

**Cascading blocks.** A change depending on a blocked one is blocked too, reason "depends on CHG-NNN." Cascades count toward the all-blocked escape hatch.

**Reviewer and implementer genuinely disagree.** Distinct from a fix round, where a finding is accepted and repaired: here they dispute whether it is a defect at all, and no number of rounds settles a disagreement about the standard. Do not spend a round re-arguing it — block with both positions summarised in one paragraph each and let the human arbitrate. The fix-round cap in SKILL.md governs rounds that are actually fixing something; this is the case that should not consume one.

**Trivial interrupted tail.** An implementer dies leaving a genuinely trivial remainder *and* a committed failing test already pinning the contract — finish it directly rather than paying for a fresh dispatch. Verify the tree first, record it in the change file, gates apply unchanged. Anything past a trivial tail gets a fresh agent.

**Reviewers must not clean the tree.** A file dirty outside a reviewer's own diff gets *reported*, never restored: another reviewer may be mid-probe on it. No `git checkout`/`restore`/`stash`, no `sed -i`, no redirecting into a tracked file. This is at the agent-definition rung rather than here for a reason — a dispatch brief once invited a reviewer to re-run a mutation and it did, while a second reviewer ran concurrently on the same tree. The lesson wasn't that the reviewer should have known better; it was that a brief silently outranked a rule.

**Scratch work.** A failed `cd` does *not* abort a bash script, so the next redirect or `git init` runs at the repo root instead. Write scratch `cd` as `cd <path> || exit 1`, and give any tool with a `--repo-root`-style argument an explicit scratch path rather than trusting its default. Falsifier: a stray file appearing in the repo root.

**Killing processes.** Terminate only what you started, by tracked ID — never `pkill -f` or a name query. A project's local stack runs servers and containers with ordinary names, and a pattern kill takes those down too. If something you didn't start is in your way, report it.

## At close

**Mixed verdicts with dependent commits.** Accepting B while rejecting A, where B builds on A, either conflicts or silently carries A's code. Check for overlap with `git log --stat` *before* asking for verdicts, and say so: "B is built on A — both or neither, or I rework B standalone." Never cherry-pick through a dependency.

**Mixed verdicts lose the batch records.** Cherry-picking accepted changes leaves the plan, review and state commits stranded on the branch. Those are records, not code, and no verdict applies to them — apply them too, and confirm `docs/batches/<this-batch>/` exists on the default branch before deleting the branch.

**Aborting.** Only the human triggers it, explicitly, and confirm first. Three options, stated concretely: discard everything (`git branch -D`, total undo); keep only accepted changes by cherry-pick; or keep the branch unmerged for reference. Unmerged changes return to the backlog, and the reason goes in the batch folder — it's mandatory audit input.

## Anywhere

**Corrupted state YAML.** Rebuild from the durable sources: `git log` for the change commits, plan checkboxes, and the last valid committed version of the file. State is committed precisely so corruption is always recoverable.

**Production is broken.** Hotfix only for real breakage — production down, or the current batch built on the broken code. Normal bugs are backlog entries. Pause at the last green commit, branch from the default branch, fix with TDD, full gates apply (a hotfix is not an excuse to skip the floor), merge, rebase the batch branch, resume. `git bisect` against change commits identifies which one introduced it and whether its criteria had a gap — that's audit material.

**No subagent tool available.** Run the same pipeline inline: read each `.claude/agents/yt-*.md` and the review checklist as your own checklist for that stage, same gates, same evidence. The roles survive even when the isolation doesn't. Mention the degradation once.

**Tooling changes mid-batch.** Frozen like scope — new dependencies with an install step wait. One exception: landing an already-approved rule at a mechanism that already exists (a gate command, a script, a hook, an agent definition) is never blocked by the freeze. Forcing a lesson to the weakest available rung because of timing is worse than no rule at all.
