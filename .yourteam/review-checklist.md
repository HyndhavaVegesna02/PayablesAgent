# Review Checklist

Loaded by yt-reviewer. Core items apply everywhere; the project section starts
empty and grows through audits, each item carrying its date and rule ID.

## Tests that lie — every member blocks

Read test bodies, not names.

1. **Rigged path** — drives a different path than the behavior it names, dodging the failing one.
2. **Over-mock** — patches the internals of the thing under assembly, or asserts only call counts. A wrong constructor argument once passed every gate while the app crashed on startup.
3. **Deleted coverage** — a contract change removed the covering test instead of rewriting it.
4. **Invented fixtures** — shape or scale not derived from a real sample, so every test sharing it validates the same wrong assumption.
5. **Dirty-tree green** — the result only reproduces with uncommitted changes.
6. **Asserting nothing** — vacuous or disabled assertions; testing the mock rather than the behavior.
7. **Right failure, wrong reason** — fails pre-patch on an import error that masks an assertion which would never have failed. The mechanical gate cannot see this one; you can.

Suspect over-mocking? Construct the real object, hit the real entrypoint, compare.

## Cross-change (why the review is batched)

- [ ] Same logic implemented twice in different changes.
- [ ] A seam that now requires the same edit in several places.
- [ ] Error handling or naming that drifted between the first change and the last.
- [ ] A pattern the first change established and a later one quietly abandoned.

## Contract enumeration — blocking when the contract trigger fired

- [ ] The plan's contract table has all four cells answered for every value the change reads: units/scale, empty, absent, failure. **An unanswered cell blocks.**
- [ ] Empty and absent are answered separately, not conflated.
- [ ] Each answer says whether it was cited from the producing code, from a probe, or from documentation. Documentation alone on the value the change most depends on is a finding.
- [ ] A test drives the absent case, not only the empty one.

## Standing checks

- [ ] Error paths: anything that can realistically fail has a handled, tested failure path.
- [ ] Empty-input behavior on functions over collections: a named domain error or a documented default, never a leaked stdlib message.
- [ ] Range and interval math tested at a non-aligned boundary, not just clean inputs.
- [ ] A port's fake and its real adapter agree on edge behavior, driven by the same contract test.
- [ ] Resource lifecycle tears down on every failure path, including partial setup.
- [ ] No module-scope side effects that can crash import or collection.
- [ ] YAGNI applies to your own suggestions.

## Project additions

<!-- Empty at setup. Items enter through audits with a date and rule ID. -->
