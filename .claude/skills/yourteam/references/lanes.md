# Lanes

Read this on entering any lane above `direct`. SKILL.md routes; this executes.

## Backlog entries

Every change gets a backlog entry before it's worked, even a `direct` one. It's cheap: an ID, a title, and acceptance criteria phrased so each one could become a test. "Works well" is not a criterion; "GET /habits returns 200 and an empty list when none exist" is.

A `direct` change needs nothing more. Above `direct`, add the **paths you expect to touch** — this is what the old estimate was secretly asking you to know, and it does three useful jobs the number never did: it tells you which knowledge notes to pull into a brief, it is what the reviewer checks scope creep against, and when it turns out wrong, that's the most valuable single input to the next audit.

**Ready** means: criteria approved, expected paths named, zero open questions. Nothing enters a batch otherwise. Defects are changes too — the repro steps become the criteria.

**When to split.** Only when a piece can't be demonstrated until another piece lands. That's the whole test. If you can't demo half of it on its own, it isn't a half. One situation makes you *ask* the question without answering it: the drafted breakdown runs past roughly eight steps. It does not split anything by itself.

Where two halves only make sense together — a consumer and its producer, the frontend and backend of one removal — keep them as one change with two parts rather than two entries. A half-landed pair is worse than neither, and there's no verdict that expresses "accept one."

---

## Lane 1: `direct`

No plan, no dispatch, no ceremony. Work the change, commit as you go, run the gates, record evidence. Done.

The point of this lane is that it exists. Most changes belong here, and routing one up out of vague diligence is the single most expensive habit this loop can develop.

---

## Lane 2: `planned`

One plan document at `docs/batches/<batch>/plan.md`, covering all the batch's `planned` changes. It holds intent and design together — there's no reason to separate them at this size.

### What a plan contains

**Intent.** One paragraph: the problem in the user's terms, and what you'd be able to observe afterward that tells you it worked.

**Program design.** This is the part most agentic workflows skip, and skipping it is why review gets expensive. Before writing implementation, sketch the shape of the code — because every one of these is a decision you'd otherwise make implicitly *during review*, which is the most expensive moment to change your mind.

Keep it light. Pseudocode and trees beat diagrams:

*File-tree diff* — so the layout stays visible:

```
 src/resource
+    ├── resource-client.ts       # NEW — wraps the API contract
+    ├── resource-client.test.ts  # NEW — request/response mapping
~    └── resource-route.ts        # MODIFIED — wires create into the UI
```

*Call-stack tree* — for any control-flow or orchestration change, with diff markers where the interesting part is what changes:

```
 entrypoint
   runCommand
+    handleCreateResource
+      ResourceClient.create(input)
-    legacyCreateFlow
```

*Types and signatures* — for the key new functions. Too internal for an architecture doc, exactly where a model guesses wrong.

**Contracts consumed** — mandatory whenever the contract trigger fired, and the one section where completeness is checked rather than assumed.

"A contract you didn't write" means: another service's API, a third-party library, an external engine, or another module's public interface. It does not mean code this same change is creating.

Scope it to the values this change actually reads — not every field the producer exposes. For each one, answer all four:

| | question |
|---|---|
| **1. Units and scale** | Seconds or milliseconds? `0–1` or `0–100`? Cited from the producing code, never inferred from the field name. |
| **2. Empty** | Empty collection, empty string, zero. |
| **3. Absent** | Null, None, missing key. **A distinct question from empty, and the one that gets skipped.** |
| **4. Failure** | What comes back when the producer cannot answer — an error, a null, or a plausible-looking wrong value? |

Four questions in a grid rather than a paragraph, because prose can be careful and silently partial while a grid with a hole in it cannot. The failure this replaces: a change identified NULL as the risk area, wrote a plan section about it, wrote a test that executed real SQL against a real engine — and still shipped a bug, because it answered the null-*element* question and never asked the null-*array* one. Nothing in the loop asked whether the enumeration was complete. Empty is not absent. A collection with nothing in it is not the same as no collection; zero is not the same as unknown.

**An answer you cannot cite is a question, not an answer.** Write it down as a question — the reviewer treats an unanswered cell as blocking. Citing the producer's own code or its own test driving that case is strongest; citing its documentation is acceptable but weaker, so mark which you did. Reading one validation layer is not proof. If you claim the producer lacks something, prove it with a probe of the failing path actually failing.

This makes one common class of divergence visible. It does not make you complete: a contract can still differ in ways none of the four name — an undocumented enum value, an ordering that isn't actually guaranteed. Add rows when you can name the question.

**Steps** as checkboxes, two to five minutes each, TDD-shaped: write the failing test, watch it fail for the right reason, minimal code, watch it pass, commit.

**Fixture sources.** Every new fixture names the real sample it came from. A fixture invented at a plausible-looking scale makes every test that uses it validate the same wrong assumption.

### Execution

**Dispatch or work it inline — decide, don't default.** A subagent buys two things: implementation churn stays out of your context, and cheaper tokens do the grunt work. It costs a cold start and a brief you have to assemble. So dispatch when the work is long or noisy; work inline when you have just written the plan and the context is already warm, which is common for a single `planned` change. Neither is the degraded option. (Where no subagent tool exists, inline is the only option — read the agent definition as your own checklist and note the missing isolation once.)

When you do dispatch, the brief carries: the backlog entry with criteria verbatim, its plan steps, the branch, and fresh knowledge notes covering the expected paths — get those with `yt_stale.py --brief <expected paths>`, which returns only the notes that are still current. Never your session history: a brief built from what you happen to remember is how one change's assumptions leak into the next.

Commit after every green step. That cadence is the recovery mechanism, so police it: check `git log` recency at each transition, and a silent gap much past half an hour means a stalled agent — kill it, check the tree, dispatch fresh from the last green commit.

Run the gates. Move on.

---

## Lane 3: `sliced`

Same plan, plus slicing — and the slicing axis is the thing to get right.

**Slice vertically, not by stack layer.** Left alone, models plan horizontally: all the migrations, then all the services, then the API, then the frontend. It looks organized and it's close to useless, because nothing is touchable until the end. You can read the tests, but you can't pull it up in a browser or hit it with curl, which is how anyone has ever actually built software.

A vertical slice goes end to end through every layer on a narrow path. The classic shape:

1. API contract serving mock data — verify with curl.
2. Frontend consuming the mock — iterate in the browser.
3. Wire the API to a service layer still serving mock behavior.
4. Migrations, service wired to the real store.
5. Business logic.
6. Error paths.

Each of those is demonstrable when it lands. That's the property that matters.

**Work one to three slices at a time, then look.** Not because a rule says so, but because resteering 150 lines is cheap and resteering 2,000 is a rewrite. Gate each slice. If a slice reveals the design was wrong, that's the slicing working — go back to the plan, don't push through.

**One implementer at a time within a change.** Slices are a dependency chain by construction — that is what makes them vertical. A later slice usually replaces the stub an earlier one stood up, and the frontend slice renders what the API slice exposed. There is nothing to run in parallel, and trying produces agents building against foundations that are about to be rewritten. Horizontal plans parallelise beautifully, which is one of the reasons they look attractive and are not.

---

## Running changes concurrently

This is an orchestration decision at the batch level, not a property of any one lane — two `planned` changes can run side by side just as two `sliced` ones can. What cannot run side by side is the inside of a single change.

**Independent changes may run concurrently.** That is where the parallelism lives: two changes in the same batch that share no files and no dependency edge. Check the expected-paths lists for overlap before you dispatch; overlap means sequential, no exceptions.

When you do run changes concurrently:

- **Every agent gets its own instance of every stateful resource** its commands touch — a database, a container, a port, a file the tests mutate. You provision it and name it explicitly in the brief. Two agents sharing one instance produce invalid signals rather than failures: interleaved writes, a table truncated mid-test, a port collision that reads as a flaky test. A gate red caused by contention is proven, not assumed — re-run the failing command in isolation, and if it passes with an empty diff since the batch cut, record the isolated run and file the flakiness as a defect.
- **Integrate serially.** One change merges onto the batch branch at a time, with the gate at each integration point. Never two gate runs at once.
- If the project has no way to provision an isolated instance, building one is early backlog material — and until it exists, run sequentially.
- **Worktree step zero is `git merge <batch-branch>`.** A worktree-isolated agent (`isolation: worktree`) is branched from the repository's *default branch*, not from the parent session's HEAD — so it starts without any of this batch's commits, not merely behind its tip. Skipping the sync means building against `main` while the rest of the batch moves on.

---

## External implementers

If someone else's agent is building to your plan, the plan is the entire contract — self-contained, conventions embedded, edge behavior per method explicit, because an external implementer builds literally and infers nothing. Three things to state at handoff and verify on return:

1. **A commit per change**, not one lump. If work comes back as an uncommitted tree, read each diff and commit it as a reviewable object *before* reviewing — a reviewer needs a stable diff, and the gate refuses a dirty tree anyway.
2. **A self-reported gate result is a claim, not evidence.** Your own gate run on the final HEAD is the only record that counts, and it routinely diverges: missed problems, a command that ran with no database, a stale HEAD.
3. **Review is never skipped here**, whatever the size. Self-review blind spots are exactly what this mode reintroduces.
