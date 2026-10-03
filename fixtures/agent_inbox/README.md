# Agent inbox

Mail that only the exception agent's tests deliver (batch 6, CHG-008). It is kept out of
`fixtures/test_inbox`, which the demo's mail poll reads, so the demo still shows the drift that
fixture 04 causes.

| File | What it is |
| --- | --- |
| 11-debit-shree-transport-missed.eml | ₹20,000 UPI debit to Shree Transport, Tue 13 Oct: the alert behind 04's ₹20,000 gap. In the drift scenario a poll ran on Thu 15 Oct first, so this message is before every later poll's window and only the agent's search finds it. The account's alert sender is unchanged. |
