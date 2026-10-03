# Batch 4 — Review

**Range:** adf655e..1696b45 (CHG-022, CHG-021, CHG-023). The review is split by subsystem into two reviewers, each bound by `.claude/agents/yt-reviewer.md`: ledger/planner/jobs, and web.

## Round 1

### Reviewer A: ledger, planner, jobs: FIX_REQUIRED

**Critical:**
1. **One debit could pay two bills.** Nothing stopped a second link of a bank_txn already held by another bill (owner-PAID or REVIEW), so the snapshot counted one debit against two bills.
   - **Fix:** `writer.transition` refuses a payable `matched_txn_id` that another bill holds ("bank_txn X already pays bill Y").
   - **Test:** `test_the_writer_refuses_to_link_a_held_debit_to_a_second_bill`.
2. **The run that lapses an authorisation was stale from birth.** It stored its hash over the snapshot with the ACTIVE row, and the next snapshot sees it LAPSED.
   - **Fix:** `effective_snapshot(s, r)`. `replan` persists the run, and works out its options, over the inputs without the lapsed authorisations; what_if uses it too.
   - **Test:** `test_c1_the_run_that_lapses_an_authorisation_is_not_stale`.
3. **Knock-on lapses.** The authorisation's own effects (a smaller bill losing its early-payment slot) could deepen the low and lapse it.
   - **Fix:** the floor is compared with the plan made without any authorisation, which is what the owner was shown.
   - **Test:** `test_c2_an_authorisations_own_knock_on_never_lapses_it`.
4. **A lapse dropped the bill's delay too.**
   - **Fix:** `_without_lapsed` drops only the authorise_breach override.
   - **Test:** `test_c3_a_lapse_keeps_the_bills_delay`.
5. **An approved (PAYMENT_EXPECTED) authorised bill no longer counted as covered,** so the authorise option came back after approval.
   - **Fix:** `_plan` adds it to `authorised`.
   - **Test:** `test_c4_an_approved_authorised_bill_is_still_covered`.

**Major:**
1. **No tests that an override ends on SPLIT or REOPENED.**
   - **Test:** `test_an_override_ends_when_its_bill_is_split_or_reopened`. The behaviour was already in CHG-021, so this test passes before the fix by design.

### Reviewer B: web: FIX_REQUIRED

**Critical:**
1. **One debit could pay two bills (web side).**
   - **Fixes:**
     - `explain_debit` settles the question when the debit is already matched or held;
     - mark_paid on a REVIEW bill settles the debit's question;
     - a single `held_debit` / `debit_holder` lookup replaces the duplicated ones.
   - **Tests:**
     - `test_one_debit_never_pays_two_bills`: the second answer gets 409;
     - `test_a_debit_settled_meanwhile_closes_its_question_and_links_nothing`.

**Major:**
1. **not_a_bill left held bills in REVIEW.**
   - **Fix:** `_release_held` returns them to PAYMENT_EXPECTED.
   - **Test:** `test_not_a_bill_payment_returns_the_held_bills_to_expected`.
2. **No test chose delay_flexible through the app.**
   - **Test:** `test_choosing_a_delay_through_the_app_gives_the_options_figures`. Electricity is made flexible; the test chooses the delay, checks the line moves Thu 15 → Mon 19 with the option's lowest balance, then undoes it. It passes before the fix by design.

**Minor (fixed):**
- No bill is preselected for a link (`test_no_bill_is_preselected_for_a_link`).
- Dates use `| day`, and the question body uses `format_day`.
- One Undo per option.
- The alias is ignored for a whitespace-only counterparty.

**Minor (deferred to the backlog):**
- authorise_breach is still offered on an invalid plan with no escalations. Restricting it breaks batch 1's `test_ask_ca_when_statutory_bills_alone_breach` contract, so the restriction was reverted.
- The `breach_on` name: it holds the day of the low, not the first breach day.
- The inputs_sha256 change makes runs made before CHG-021 stale once.
- No extra confirmation for a large debit/bill difference. The difference is shown in the reason text.
- `asked_note` is tested only through `repo.options`, not through a page.
- The alias checkbox shows even when the names match. In that case it is ignored.

### Fix commit

d016650. The gate is recorded under CHG-022: green, 904 passed, ruff clean, 5 contracts kept.

`yt_prepatch --since 1696b45 --to d016650`: PASS. 10 tests fail at 1696b45. The two coverage tests above pass there by design.

## Round 2: lean re-review of d016650 (one reviewer): FIX_REQUIRED

Every round 1 fix was confirmed, but the C2 fix introduced a regression.

**Critical:**
1. **A second authorisation lapsed as soon as it was chosen.**
   - **Cause:** the floor is the low of the run the owner saw, which already had the earlier authorisations applied. Round 1 compared every floor against the plan with no authorisation at all. When an earlier authorisation changed an early-payment discount decision, the later one's floor sat above that baseline, so the owner could never authorise it. The reviewer verified this with a probe.
   - **Fix (f9a14fc):** `plan()` checks the authorisations in the order chosen. Each is measured against the plan with only the earlier, still-kept authorisations, which is exactly what the owner saw. `build_snapshot` reads overrides `ORDER BY id`. The reason text uses each authorisation's own baseline. C2 still holds, because neither its own knock-on effects nor those of later authorisations count.
   - **Test:** `test_a_second_authorisation_is_measured_on_the_plan_the_owner_saw`.

**Minor (deferred to the backlog):**
- An approved (PAYMENT_EXPECTED) authorised bill can lapse on a deeper breach. Approved bills have no plan line, so the D18 reason text shows nowhere and the options come back. This overlaps the deferred authorise_breach minor.

### Fix commit

f9a14fc. The gate is recorded under CHG-021: green, 905 passed.

`yt_prepatch --since 1aa376b`: PASS. The new test fails at 1aa376b.

## Round 3: lean re-review of f9a14fc: FIX_REQUIRED

Round 2's critical was confirmed fixed, and hash consistency and purity hold. This round's finding has the same root cause as round 2's: the baseline differed from the plan the owner saw. So it is the reviewer's earlier sweep being incomplete, not a new failure to converge.

**Critical:**
1. **One authorise choice covering several escalated bills lapsed all but the first.**
   - **Cause:** Q6 records one override per ESCALATE bill, all with the same run's low. Round 2 measured them one after another, so the first override's discount knock-on lapsed the second. The reviewer verified this with a probe.
   - **Fix (5e3720d):** `OverrideIn.choice_id` comes from `plan_override.shortfall_option_id`. A choice's overrides share one baseline: the plan with only the earlier kept choices.
   - **Test:** `test_one_choice_covering_two_bills_is_measured_as_one`.

### Fix commit

5e3720d. The gate is recorded under CHG-021: green, 906 passed.

`yt_prepatch --since b908f06`: PASS. The new test fails at b908f06.
