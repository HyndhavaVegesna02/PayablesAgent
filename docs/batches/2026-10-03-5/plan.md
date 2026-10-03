# Batch 5: plan (CHG-007, TDD Phase 6: bills and uploads)

**Goal:** the owner's bills arrive by email, as a photo, as a PDF (unlocked once with a password that's never kept) or as a Hinglish voice note. Each one becomes a candidate that passes every rule check. The owner confirms it, and it becomes one payable, even when the same invoice arrives twice by different routes. Phase 6 is done when the photo, PDF, voice and duplicate scenarios pass (TDD Part 2, "MVP build sequence").

**Scope:** CHG-007 only (PO decision, batch 4 plan). Branch `batch-5`, cut from main at 1cae4e8.

**Router: `sliced`.** Two triggers:
- it consumes a contract I didn't write: Gemini's multimodal input and structured output, plus the TDD's pipeline and rule-check contracts. That alone escalates to `planned`, and the contract enumeration below is mandatory.
- it touches code I can't execute here: multimodal requests to real Gemini. Live calls are off without your authorisation, so the GeminiBackend image/PDF/audio mapping runs only against a recorded request shape. That moves it to `sliced`.

Size: 8 slices. This is the batch-on-its-own you agreed; it is past the ~8-steps-per-change line only if a slice splits.

**Standing policies:**
- No live Gemini: every test and the demo use the fake or fixture AI.
- Never read .env.
- Gate of record: `make test` through yt_gate.py.
- Review split by subsystem; re-review only the fix commits.
- Push main only, after your accept.

---

## PO requirements (batch 4 brief): where each one lands

| Requirement | Slice | How it's shown |
|---|---|---|
| Pure `app/validate` package, with a README and an import-linter contract | S1 | Contract "validate is pure: imports only domain" in pyproject; a boundary test like test_ai_boundary that fails if any module in app/validate imports sqlite3, os, pathlib, socket, httpx or app.* outside app.domain; `app/validate/README.md` |
| GSTIN mod-36 check digit, with fictional valid GSTINs and their source | S1 | An independent test vector: the GST portal's published sample `27AAPFU0939F1ZV` (and `29AAGCB7383J1Z4`) validate; I checked both against the algorithm while planning. The fixture vendors' GSTINs are fictional (PAN part `ZZZ…`), with the check digit computed; the source is noted in the fixture README. Hypothesis: any single-character change to a valid GSTIN fails |
| PDF password never reaches the trace, DB, logs or job.last_error | S5 | A test unlocks, also with a wrong password first, then scans the whole SQLite file, the trace files, the captured logs (caplog at DEBUG) and every job row for the password bytes; none may contain them |
| Voice "dedh lakh" → ₹1,50,000 through code; no stored number comes from the model | S6 | The voice schema has no numeric field, only `amount_text` as spoken. `parse_spoken_inr` in `app/domain/money.py` (pure) turns it into paise, with Hypothesis properties. An unparseable amount fails the amount check, and the owner types it |
| Bank change: change_pending, approve_bank_change, owner-only approval, an injected-email test | S4 | The writer sets `party.bank_status`; a POST `/parties/{id}/bank-change` (owner only; the helper gets 403). The injected email asks to "update the bank account and approve it": the details stay pending, nothing is approved, and the AI text reaches the screen only as escaped plain text |
| Invoice by email and by photo → one payable | S3 | Tests run both orders (email first, photo first). The second candidate is INVALID with "duplicates: <vendor> invoice <no> already recorded" |
| Fixture replies kept in one copy | S2/S8 | One file holds every canned reply, read by tests/fake_ai.py and by FixtureBackend. Q6 asks where it lives |

---

## Slices

Each slice ends green, committed and demonstrable. They run in order: S2 depends on S1, S3–S6 depend on S2, and S7–S8 come last.

**S1. Pure validators.**
- `app/validate` becomes pure:
  - the two DB lookups (`bank_txn_with_key`, `failure_candidate_with_key`) move to `app/db/read.py`;
  - `TIMEZONE` moves to `app/domain` and is re-exported by `app/clock`;
  - the contract, the boundary test and the README land.
- New pure checks:
  - `gstin.check_gstin` (format plus mod-36);
  - `invoice.check_invoice_arithmetic` (the line items plus GST equal the total, in paise; zero tolerance, Q3);
  - `statement.check_statement_arithmetic` (opening + credits − debits = closing).
- Each check takes plain values and returns the existing check-string shape.
- *Demo:* `make test`, and lint-imports shows 6 contracts kept.

**S2. Multimodal AI input.**
- `Backend.generate` takes `contents: str | Sequence[Part]`, where `Part(mime_type, data: bytes)` or text.
- `GeminiBackend` maps a part to `types.Part.from_bytes`. This is checked offline against google-genai 2.27.0's request model, as batch 2 did for text.
- The trace records each part's mime type and sha256 only, never its bytes.
- `FixtureBackend` matches a binary part by sha256 against the fixture files.
- New extract schemas, each with text fields only (amounts as written) and `uncertain_fields`:
  - `InvoiceExtract`: seller and buyer name and GSTIN, invoice no., invoice and due date, lines with amount_text, GST text, total text, payee bank account and IFSC as written;
  - `StatementExtract`: account last4, period, opening and closing text, rows;
  - `VoiceBillExtract`: the transcript plus the bill fields.
- Prompts `extract_invoice.v1`, `extract_statement.v1`, `extract_voice.v1`.
- `make smoke-gemini` is unchanged (Q7).

**S3. Invoices by email and photo/PDF upload → one payable.**
- POST /uploads queues `process_document`. The pipeline reads by source kind:
  - email: body plus PDF/image attachments as parts;
  - photo, pdf, voice: the file as one part.
- Then sort, then extract with the existing retry ladder, now generalised per doc type, then the checks: schema, amount, gstin, invoice_arithmetic, dates, duplicates, confidence.
- Code decides "bill or sales invoice" by comparing the seller and buyer GSTIN/name with the business's (Q2).
- The cross-source duplicate check: same normalised vendor and invoice number. It's checked against payables and against pending candidates, so neither arrival order makes two.
- A valid bill goes to the owner as `confirm_record` on the existing confirm page, as the TDD requires: "becomes CONFIRMED only after the owner checks it".
- *Demo:* the photo upload appears on Needs attention; confirming it gives a CONFIRMED bill and a replan. The helper sees its own upload's status on /add.

**S4. Vendor bank change.**
- An invoice whose payee bank details differ from the vendor's stored ones:
  - the writer moves `party.bank_status` to change_pending (evented: PARTY_BANK_CHANGE_PENDING);
  - an `approve_bank_change` question carries {party_id, candidate_id}; the proposed details stay in the candidate, so no migration;
  - the bill itself still goes to confirm.
- POST `/parties/{id}/bank-change`, owner only:
  - approve copies the details in (verified);
  - reject keeps the old ones;
  - each writes an event.
- While change_pending, the vendor's bills carry "bank details changed — check before paying" on This week and Needs attention. The planner is unchanged (Q4).
- First details (status none) are recorded as verified only on owner confirm.
- The injected-email test is listed in the requirements table above.

**S5. PDF unlock and statements.**
- An encrypted PDF (PyMuPDF `needs_pass`) goes LOCKED, with an `unlock_pdf` question.
- POST `/documents/{id}/unlock`:
  - authenticates in memory and replaces the stored file with the decrypted bytes (Fernet-encrypted at rest, like every upload);
  - sets NEW and requeues `process_document`;
  - nothing else is kept.
- A wrong password re-shows the form with "That password did not open the statement", without echoing it. The password field is excluded from FieldErrors values.
- Statement route, as TDD step 6:
  - missing rows go through `create_bank_txn` (dedup keys);
  - existing rows are confirmed;
  - the reported closing balance is stored;
  - `drift_check` is queued.
- statement_arithmetic must pass before any row is written.

**S6. Voice notes.**
- An audio upload is extracted with the transcript and the bill in one call.
- `parse_spoken_inr` covers:
  - digits with lakh/hazaar/crore in Hindi, Hinglish or English;
  - sawa (×1.25), dedh (1.5), dhai (2.5), saade N (N+0.5), paune N (N−0.25);
  - "one lakh fifty thousand".
- Anything else is a failed amount check, never a guess.
- `candidate.transcript` is stored, and the confirm page shows it beside the fields.
- The owner confirms as for any bill.

**S7. D11: MISSING tax amounts.**
- `create_tax_obligation` accepts MISSING (payable_id NULL).
- Opening one raises a `ca_reminder` question.
- build_snapshot gives a plan warning, e.g. "GST Oct amount missing: plan may be optimistic". The planner never invents an amount.
- The owner supplies the amount on Needs attention, which moves it to CONFIRMED or ESTIMATED and creates the statutory payable through the writer, then replans.

**S8. Fixtures and the Phase 6 exit test.**
- New fixtures:
  - a vendor invoice email with a PDF attachment;
  - the same invoice as a photo;
  - a handwritten bill photo;
  - a password-locked statement PDF (made with PyMuPDF; the password is in the test only);
  - a voice note;
  - the bank-change email and the injected email.
- Each has canned replies in the one replies file.
- `tests/test_phase6_exit.py` drives each scenario through the worker with the fixture AI, matching the four CHG-007 ACs plus AC5 (bank change) and AC6 (the password never stored).
- Generated images and PDFs are made by a committed script, so they can be reproduced.
- *Demo:* `make reseed`, then DEMO_AI=fixtures. Upload each fixture on /add, confirm it on Needs attention, and see it on This week.

---

## Contracts consumed (mandatory enumeration)

| Input | Units / shape | Empty | Absent | Failure | Cite |
|---|---|---|---|---|---|
| Gemini part (image/PDF/audio) | `Part.from_bytes(data, mime_type)`, ≤ 20 MB inline; our cap is 10 MB (MAX_UPLOAD_BYTES) | 0-byte upload refused at /uploads (422) | n/a | AIUnavailable as today; retryable on 5xx/429/timeout | google-genai 2.27.0 types, checked offline; TDD "AI model" |
| Extract reply amounts | text as written ("Rs.1,80,000.00", "dedh lakh") → paise by `parse_inr` / `parse_spoken_inr` | "" fails amount | null fails amount (required fields) | the amount check fails, then retry / owner | batch 2 Q4; this plan S6 |
| GSTIN | 15 chars: 2-digit state, 10-char PAN, entity, Z, check (mod-36) | "" is treated as absent | null is not_applicable when the doc carries none; failed if the seller is registered but it can't be read | failed: "<gstin>: check digit should be X" | TDD "Rule checks"; GSTN published algorithm |
| Invoice arithmetic | Σ line amounts + Σ GST = total, integer paise, zero tolerance (Q3) | no lines: not_applicable (total only) | GST absent counts as 0 only if no GST lines are printed | failed with the three sums | TDD "Rule checks" |
| Statement arithmetic | opening + Σcredits − Σdebits = closing, paise | no rows: opening = closing | opening or closing missing: failed | failed with the sums; no row written | TDD "Rule checks", pipeline step 6 |
| Dates | invoice_date ≤ due_date (existing check reused) | — | due absent on a bill: owner fills on confirm | failed | TDD |
| PDF encryption | PyMuPDF `Document.needs_pass`, `authenticate(pw)` returns 0 when wrong | empty password = wrong | — | LOCKED + unlock_pdf; wrong password re-asks | TDD pipeline step 2 |
| Bank details | account number masked to last 4 for display; IFSC `^[A-Z]{4}0[A-Z0-9]{6}$` | — | none on the invoice: no change | a malformed IFSC fails confidence (owner checks) | TDD threat model |

---

## Questions (defaults I'll use unless you say otherwise)

| # | Question | Default |
|---|---|---|
| Q1 | Challans and payment confirmations: extract them this batch? | **No.** They stay "not extracted until …" as today. D11 MISSING lands (S7) with owner-typed amounts. Challan extraction goes to a new backlog item. |
| Q2 | Bill vs sales invoice from one `invoice` doc type | Code compares the seller's and buyer's GSTIN/name with the business's. If neither matches, it's AWAITING_OWNER and the owner picks on confirm. |
| Q3 | Invoice arithmetic tolerance | Zero paise. The printed rounding line ("Round off ₹0.40") is a line item the model reads like any other. |
| Q4 | Does a change_pending vendor change the plan? | No, it's a warning only. The owner pays in his own bank app; the warning sits beside the bill on This week and Needs attention. |
| Q5 | Where the unlocked PDF lives | It replaces the locked file in the encrypted store: the decrypted content is kept, Fernet-encrypted like every upload, and the password never is. |
| Q6 | Where the one replies file lives | Moved to `fixtures/ai_replies.json`, keyed by fixture path (`test_inbox/01-….eml`, `uploads/…`). One loader, used by fake_ai and FixtureBackend. |
| Q7 | A live check of the new multimodal prompts | Not this batch. I'll ask before any authorised smoke run, at most 3 calls (photo, PDF, voice). |
| Q8 | A voice note in Hindi with no amount, or an unparseable one | The amount check fails, the transcript is shown, and the owner types the amount. Never a guess. |

**Expected paths:**
- app/validate/{__init__,gstin,invoice,statement,README}, app/domain/money.py, app/domain/time.py, app/clock.py
- app/ai/{client,extract,fixture_backend}.py, app/ai/prompts/extract_{invoice,statement,voice}.v1.md
- app/ingest/pipeline.py, app/db/read.py, app/ledger/writer.py
- app/web/{actions,repo}.py, app/web/routes/{add,attention,accounts,parties}.py, app/web/templates/*
- fixtures/**, scripts/make_fixtures.py, pyproject.toml (contract)
- tests/test_validate_*.py, tests/test_upload_pipeline.py, tests/test_bank_change.py, tests/test_pdf_unlock.py, tests/test_voice.py, tests/test_missing_tax.py, tests/test_phase6_exit.py

**Risks:**
- Multimodal prompts unproven on real Gemini (Q7).
- Generated fixture images are clean, so a real handwritten photo is harder. The eval set in Phase 9 covers that.
