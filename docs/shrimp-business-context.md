# The shrimp farm: business context for the demo

Background for presenting the shrimp-farm demo: the crop's life cycle, who the actors are, and which
part of the cycle the demo plays. The moves and the exact on-screen text are in
[demo-shrimp.md](demo-shrimp.md); building the presenter page is in
[handoff-demo-presenter.md](handoff-demo-presenter.md).

All names are fictional. The cycle and practices are typical of vannamei (whiteleg shrimp) farming in
coastal Andhra Pradesh, around the Godavari and Krishna deltas (Bhimavaram, Akividu, Kaikaluru);
details vary from farm to farm.

## 1. One crop, about four months

| Stage | When | What happens | Money |
| --- | --- | --- | --- |
| Pond preparation | two to four weeks before stocking | drain, dry and lime the pond, refill and treat the water, install aerators | lease, labour, lime and treatment |
| Stocking | day 0 | buy post-larvae ("seed") from a hatchery and release them into the pond | seed, often on credit from the dealer |
| Grow-out | day 1 to about day 110 | feed several times a day, run the aerators day and night, check the water, sample growth, fight disease | **feed is the biggest cost**, usually on credit from the feed dealer; electricity for the aerators, the caretaker's wages, diesel for the generator in power cuts, repairs |
| Harvest | about day 100 to 120 | net the pond, ice the shrimp at once, weigh them at the pondside (the weighment slip), grade them by **count**: pieces per kilogram, where a lower count means bigger shrimp and a higher price | the buyer's agent pays an **advance** |
| Settlement | one to two weeks after harvest | the processor or exporter re-checks the count and the quality; the agent pays the **balance less deductions** | re-grading, soft shell, ice and crew, commission |

### Why the harvest fortnight is the danger zone

- A whole season of credit falls due at once: feed, seed, the lease, wages, power.
- The money arrives in pieces: an advance first, then the balance later, often short.
- The amounts are the largest of the year, which also makes it the moment a fraudster would try to change
  a vendor's bank account.
- The paperwork is bank SMSes and emails, WhatsApp voice notes, and handwritten slips.

## 2. The actors

| Actor | Who they are in real life | In this scenario | In the app |
| --- | --- | --- | --- |
| Godavari Aqua Farm | the shrimp farmer, the business owner | must pay everyone on time without the bank balance falling below the ₹50,000 safety amount | **owner**: confirms bills, decides, approves payments, pays in their own bank app |
| Lakshman | caretaker or pond watchman, paid a monthly wage | sends the diesel bill as a Telugu voice note and the repair slip as a photo | **helper**: can only add bills |
| Sri Lakshmi Aqua Feeds | the feed and seed dealer, who gives the season's feed on credit | last feed delivery ₹25,000; the season's settlement ₹6,46,800, "pay within 5 days", from a **new bank account** | vendor |
| Ravi Traders | the commission agent who sells the harvest to a processor and pays the farmer | harvest of 4,500 kg at 55 count, ₹270 a kilogram, ₹12,15,000 gross; an advance of ₹2,00,000 from Ravi's **personal UPI**; the balance paid ₹9,20,000, **₹95,000 short** | customer |
| The processor or exporter | the plant that buys from the agent and re-grades the shrimp | off stage; its re-grading causes the deductions | not in the app |
| K. Subba Rao | the landowner who leases the pond land | lease instalment ₹75,000, due Sat 31 Oct; asks for it early | vendor |
| APSPDCL | the state's power distribution company | the aerators' electricity bill, ₹15,000 | vendor |
| Raju Petrol Bunk | the local fuel station | generator diesel, ₹3,000 (the voice note) | vendor |
| Venkat Motors | the aerator and pump repair shop in Bhimavaram | aerator motor rewinding and parts, ₹18,000 (the photo of the slip) | vendor |
| HDFC Bank | the farm's bank | emails a credit or debit alert for every transaction | the source of truth for the balance |
| PayablesAgent | the assistant | reads everything, keeps the ledger, plans 14 days ahead, investigates what doesn't match. **It never moves money** | the system |

### How the short payment adds up

| | Amount |
| --- | --- |
| Balance due | ₹10,15,000 |
| Re-grading (55 to 60 count) | − ₹22,500 |
| Soft shell | − ₹24,300 |
| Ice and harvest crew | − ₹20,000 |
| Agent's commission | − ₹28,200 |
| **Paid by NEFT** | **₹9,20,000**, short by ₹95,000 |

## 3. What the demo plays, and what it doesn't

The demo plays **weeks 15 and 16 of the crop**: the harvest and settlement fortnight, Mon 19 to Mon 26
Oct 2026, on a frozen demo clock. Pond preparation, stocking and the grow-out happened before the demo
starts: it begins from the farm's bank balance and the bills and money still outstanding.

| The real-life problem | In the demo | What the system does |
| --- | --- | --- |
| Money arrives under a name the books don't know | the advance comes from "RAVI K" by personal UPI (Tue 20 Oct) | the agent searches the mailbox, finds the weighment slip and shows its finding; the farmer links the credit |
| A big bill lands at the worst moment | the dealer's ₹6,46,800 settlement, due in 5 days (Wed 21 Oct) | the plan shows the shortfall days ahead and offers options: ask the buyer to pay early, split the bill, or go below the safety amount |
| A payment-redirect attempt | the dealer's invoice gives a new bank account | code holds the old account until the farmer decides; the farmer rejects the change |
| Bills arrive informally | a Telugu voice note and a photo of a handwritten slip (Thu 22 Oct) | the AI reads them, code checks them, the farmer confirms |
| Pressure to pay early | the landowner wants the lease this week | the plan keeps it on its due date, since paying now would deepen the shortfall |
| The buyer pays short | ₹95,000 deducted from the balance (Fri 23 Oct) | the agent finds the payment advice that explains it; code records the gap and the plan recovers |

The fortnight closes when the dealer's payment leaves the bank (Mon 26 Oct) and the bill is marked paid
by itself.

## 4. A one-minute opening for the panel

> "This is Godavari Aqua Farm, a shrimp farm in the Godavari delta. A crop takes about four months, and
> the farmer runs it on credit: the feed dealer supplies a whole season of feed and settles at harvest,
> and the land lease, the electricity for the aerators, the caretaker's wages and the repairs keep coming.
> All the money comes in at the end, through a commission agent who sells the harvest to a processor. He
> pays an advance on harvest day and the balance a week or two later, after the processor re-grades the
> shrimp, and usually short.
>
> So the harvest fortnight is the most dangerous two weeks of the year: everything falls due at once, the
> money arrives in pieces, under names the bank doesn't recognise, and the paperwork is SMSes, WhatsApp
> voice notes and handwritten slips. That's the fortnight we'll live through now: Monday the 19th to
> Monday the 26th of October, weeks 15 and 16 of the crop. Watch what the system reads, what it works out
> on its own, and where it stops and asks the farmer."
