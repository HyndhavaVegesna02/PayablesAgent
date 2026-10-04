# Invalid: live ablation v2 reports scored after the model became unavailable

**These are not measurements.** Nothing here appears in any table or headline.

On 2026-10-04 the live ablation v2 ran from main at c4cf5f2. Partway through
the `no_case_file` invocation, at scenario 02 (its job 11), the account's Gemini
prepaid credits ran out. From then on, every model call came back
`402 RESOURCE_EXHAUSTED: Your prepayment credits are depleted`. Each trace
records it as `not run: AI unavailable (permanent, 402)`.

The run did not stop, and the scores it kept are wrong. Every run after that
point was scored as if the harness had failed, at zero cost, when the model had
never answered. The three reports kept here:

- `2026-10-04-live-ablation-v2-no_case_file/`: only scenario 01 ran before the
  402s began. From scenario 02 onward the scores reflect a model that was
  unavailable, not one without a case file.
- `2026-10-04-live-ablation-v2-no_planner/` and
  `2026-10-04-live-ablation-v2-all_tools/`: these ran entirely on 402s. Every
  "failure" is an unavailable model.

The bare harness and four knock-outs (`no_rule_checks`, `no_escalation`,
`no_drift_rule`, `no_evidence_gate`) left no report. Each crashed while copying
its first run's traces, because the destination path ran past Windows' 260-character limit
(the output folder was deep, and the trace layout nests a harness folder,
then the run). Bare's one run happened while the credits still held. Its cost
went with its report.

Two defects caused this. Both are fixed in batch 18, before the ablation runs
again:

1. **The budget guard stopped on a spend-cap 429 but not on a 402
   credit-depleted error.** It now stops the invocation at once and names the
   reason. A run in which the model was unavailable is scored ERRORED, never
   FAILED, and doesn't count toward a harness's success rate.
2. **Trace copies could exceed Windows' MAX_PATH.** They now use a shorter
   layout, and the long-path prefix where needed.

The valid part of v2 is the full system: `../../2026-10-04-live-ablation-v2-full/`
(aborted on its cost cap) and `../../2026-10-04-live-ablation-v2-full-11/`,
combined with the rest of v2 in `../../2026-10-05-live-ablation-v2/`.
