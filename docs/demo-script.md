# Demo script (3 minutes)

A script for recording the demo. Nothing has been recorded. It runs offline in
demo mode (`DEMO_NOW=2026-10-12T09:00:00+05:30`, `DEMO_AI=fixtures`; see the
README's Quickstart), after `make reseed`, with `make run` and `make worker`
in two terminals and a third for `make demo-time`. The times on the left are
targets for the recording, not measurements.

| Time | Show | Say |
| --- | --- | --- |
| 0:00 | The week page, logged in as the owner | "A small manufacturer's next 14 days of payments. The AI reads mail and uploads; code owns every number; the owner approves and pays from their own bank app. The app never moves money." |
| 0:20 | The plan's warning and its options | "The lowest balance dips under the safety amount next Thursday. The planner, which is plain code, offers ways out. I'll ask a customer to pay early, then approve today's payment." Click *ask Nandi Foods to pay early*, then *Approve*. |
| 0:45 | Terminal: `make demo-time T=2026-10-12T12:00:00+05:30`, then refresh | "The bank's debit alert arrives. The AI reads it, code checks it, and it matches the approved payment, so the bill is paid. A re-sent copy is caught as a duplicate." |
| 0:55 | `make demo-time T=2026-10-13T23:00:00+05:30`, then *Needs attention*: confirm invoice AP/2610/131, then approve its bank details | "Tuesday: the supplier's invoice arrived by email. I confirm the bill. Its bank account is the first we've seen for this supplier, so that's a separate decision: I'd check by phone, then approve it, and it becomes the one on record." |
| 1:05 | `make demo-time T=2026-10-14T11:00:00+05:30`, then *Needs attention* | "Wednesday: the bank returned that payment. The bill is reopened and the plan updated. And the supplier emailed new bank details, with a line telling the AI to approve them. Nothing changed: the details on record stay, and only I can accept the new ones." |
| 1:35 | `make demo-time T=2026-10-15T23:00:00+05:30`, then *Needs attention* and the week page | "Thursday: the bank's balance is lower than the books. The assistant couldn't explain the gap, so code asks me for the real balance, and plans from the lower figure in the meantime." |
| 2:00 | [docs/traces/success.jsonl](traces/success.jsonl) next to [its walkthrough](traces/README.md) | "When the missing alert is in the mail, the agent finds it. Here's the trace: it searches, proposes the record, and code checks the evidence before anything is written. Line 19 is the control point." |
| 2:25 | [docs/threat-model.md](threat-model.md), the attack section | "We ran the attack from the brief with a fully hijacked model. Every tool it tried that isn't one of its five was refused, the record it proposed failed its checks, and nothing changed. What reached the owner was its false summary, shown as plain text." |
| 2:45 | [docs/evals/](evals/README.md), the ablation report | "Every TDD scenario runs repeatedly at three levels. The ablation compares the full harness against a bare loop and seven knock-outs. The figures are in the reports, with the commit they came from." |
| 3:00 | End | |
