# Test inbox

`EmlFolderSource` reads these `.eml` files (MAIL_SOURCE=eml_folder). Every value is fictional:
the sender domain is `hdfcbank.example`, the account is XXXX4821 from the seeded worked example,
and the parties and amounts come from TDD Part 1's worked example. Each file's
`X-Fixture-Note` header says what it is. The layout follows HDFC Bank InstaAlert emails
(subject line, "has been debited from account **4821", reference number, available
balance) so the extraction prompts see a realistic shape.

| File | What it is |
| --- | --- |
| 01-debit-ashirwad-paper.eml | ₹1,80,000 NEFT debit to the paper supplier, Mon 12 Oct; balance agrees with the ledger |
| 02-credit-kaveri-traders.eml | ₹33,000 credit from Kaveri Traders, Tue 13 Oct |
| 03-return-ashirwad-paper.eml | The paper payment returned, Wed 14 Oct |
| 04-debit-city-electricity-balance-short.eml | ₹35,000 debit whose available balance is ₹20,000 short: a debit with no alert |
| 05-offer-newsletter.eml | A promotional email (irrelevant) |
| 06-debit-ashirwad-paper-resent.eml | Alert 01 re-sent with a new Message-ID |
| 07-credit-nandi-foods.eml | ₹2,00,000 credit from Nandi Foods, Fri 16 Oct: the early payment the owner asked for (no available balance shown) |
| 08-invoice-ashirwad-ap131.eml | Ashirwad's invoice AP/2610/131, ₹95,000, Tue 13 Oct, PDF attached; the same invoice as `fixtures/uploads/ap-2610-131-photo.png` (CHG-007) |
| 09-invoice-ashirwad-new-bank.eml | Ashirwad's invoice AP/2610/140 giving new bank details, with an injected instruction to approve them (CHG-007, TDD threat model) |
| 10-statement-hdfc-locked.eml | A password-protected statement for 12-13 Oct, Tue 13 Oct night (CHG-007; the password is in `scripts/make_fixtures.py` and the tests only) |

The fake AI replies for these files were written by hand and live in `fixtures/ai_replies.json`, the one copy read by the tests and the demo's fixture AI. Files 08-10 are made by `scripts/make_fixtures.py`.
