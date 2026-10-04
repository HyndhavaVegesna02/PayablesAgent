# Superseded: the fixture reports before batch 17

Generated at 10d29b1 (the two suites and the ablation at their own commits, as
each header says). They were replaced at batch 17's HEAD because batch 17
changed what the reports say:

- the suite has three harder scenarios (12 to 14, fixture-only, not yet run
  live), so the two suites and the ablation have more rows;
- every agent scenario has path budgets, so the reports carry more checks;
- the ablation has three more knock-outs (`no_case_file`, `no_evidence_gate`,
  `all_tools`);
- in the scripted attack on scenario 10 and workflow B, the agent first claims
  the case RESOLVED citing nothing, and code refuses that before it is passed to
  the owner. That is one more agent turn, so workflow B makes one more model call.

They are kept as they were, for comparison. The current reports are one
folder up.
