# Batch 20 plan: docs/evals by deliverable

PO direction, user-approved (2026-10-06). One change, CHG-055, planned lane: the move changes paths the
public repo's pages link to. No Gemini calls; no measured result changes.

1. evals/layout.py names the folders; make evals and make ablation write to raw-runs/, make workflow to
   4-end-to-end-workflows/.
2. evals/report.py: a combined report's sources are paths under docs/evals; the suite page gets a Coverage
   line (scored of planned, invocations and commits, every replaced row with its earlier results); both
   combined pages give a plain status, true to the recorded reason, and the runs each source gave; the
   ablation page gives coverage per harness, shows a paired drop only above half the scenarios, and says
   what "earned the most" rests on. The totals wording uses one denominator.
3. check_evidence walks the numbered folders and raw-runs, recursively, and resolves sources by path.
4. The move: live reports by `git mv` alone; the fixture suites regenerated (the totals wording); the two
   combined pages regenerated from the moved parts. In this tree the v1 ablation's parts and table go to
   raw-runs/ too, so check-evidence still checks it.
5. READMEs: "Start here" and one per numbered folder; each figure asserted by a test against its report.json.
   Every link and path fixed; a test that every relative link in README.md and docs/**/*.md resolves.
6. Scenario 04's history checked offline, commit by commit.

Gates: make test and make check-evidence, then the public tree as one commit on public-ui.
