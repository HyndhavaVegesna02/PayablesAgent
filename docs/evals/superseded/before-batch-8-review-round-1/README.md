# Superseded: the ablation before batch 8's review round 1

Generated at 2142c95. Batch 8's fix round 1 (7c80499) changed how the eval scores the
owner's form refusing an entry: a rule-check refusal is now blamed on validate, not on what
was read, and the message no longer says "as it was read". One run's error text in this
report.json changed with it; nothing else did. The other fixture reports reproduce unchanged.

Kept as it was, for comparison. The current report is in ../../2026-10-04-fixtures-ablation/.
