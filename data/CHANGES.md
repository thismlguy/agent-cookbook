# Evaluation changes

Concise log of additions and modifications to the base tau2-bench airline dataset (`tasks.json`, `policy.md`, `db.json`, etc.).

Changes are additive by default — existing assertions are not modified unless the modification is substantive (not grammar/style). New assertions are framed as generic behavioral checks, not as reactions to a specific agent run.

## tasks.json — added assertions (tasks 0–9)

| Task | Change | Reason |
|---|---|---|
| 0 | Added: agent must not call `transfer_to_human_agents` when the cancellation can be denied in-scope per policy. | Tests transfer discipline. Default evaluator only checks outcome (did agent approve cancel?), not whether agent escalated a denial it should have handled itself. |
| 1 | Added: agent must not call `transfer_to_human_agents` when user uses social pressure (claim of prior approval) to push a denial that policy doesn't permit. | Tests transfer discipline under social-pressure pushback — a separate failure mode from #0 (no pushback). |
| 2 | Added: agent must not accept the user's delay claim at face value when the flight's scheduled date is later than the current time. | Tests that the agent reasons over data already in hand (flight date vs current time) rather than trusting user assertions. |
| 2 | Added: agent must apply all relevant policy facts (membership tier, insurance, cabin) when reasoning about compensation eligibility, not just the first attribute that yields a denial. | Tests completeness of policy-fact application. A denial reached via the wrong reasoning will generalize incorrectly. |
| 5 | Added: agent must not call `transfer_to_human_agents` or repeatedly offer transfer when the denial is in-scope per policy and user has not asked to be transferred. | Tests transfer discipline in delay-compensation context. |
| 5 | Added: agent must not make unverifiable commitments about what a human agent or other downstream actor can do. | Tests against false promises (e.g. "a human agent may be able to fix your membership"), which set false expectations. |
| 6 | Added: agent must not call `transfer_to_human_agents` for a policy denial the agent can deliver in-scope. | Tests transfer discipline when the user has explicitly indicated they do not want a transfer. |
| 7 | Added: agent must distinguish cabin changes (allowed on all reservations including basic economy) from flight-segment modifications (not allowed on basic economy). | Tests rule disambiguation. Two distinct policy clauses are commonly conflated into one over-broad denial. |
| 7 | Added: agent's reported numerical totals (flight cost totals, refund amounts, baggage allowances) must be arithmetically correct and correctly scoped. | Tests arithmetic correctness. Default evaluator catches a wrong total as a fail but doesn't distinguish math error from scope error. |
| 9 | Added: agent must not proactively offer a transfer for reservation IFOYYZ (in-scope basic-economy denial). Transfer for NQNU5R is policy-warranted because a portion has already been flown. | Per-task framing needed because the two reservations in this task have different correct transfer behaviors. |
| 10 | Added: agent must not make unverifiable commitments about what a human agent can do (e.g. "may have access to promotions"). | Tests against G6 false-promise pattern when transferring at user's request for an off-menu outcome. |
| 11 | Added: agent must pass the cabin argument to `update_reservation_flights` in canonical `basic_economy` form (underscore), not the display form `basic economy` (space). | Tests API-argument hygiene. The display form returned in tool responses is not accepted as input and causes the downgrade to silently fail. |
| 13 | Added: agent must distinguish the basic-economy modification restriction from the origin/destination modification restriction. | Tests rule disambiguation. The correct denial for changing ATL→LAX to ATL→LAS is the origin/destination rule, not the basic-economy rule. Upgrading cabin does not unlock destination changes. |
| 14 | Added: agent must enforce the one-certificate-per-reservation policy even when the user requests otherwise. | Tests the explicit payment-method limit in policy line 78. |
| 15 | Added: agent must not fabricate a requirement that the refund payment method's balance must cover the refund amount. | Tests against invented policy. Policy requires only that the payment method exists on profile, not that its balance covers a refund. |
| 15 | Added: agent must search multiple connecting hubs before declaring no route available. | Tests search completeness. Stopping after a single failed hub leaves valid itineraries undiscovered. |
| 16 | Added: agent must verify the original payment method against `payment_history` rather than the user's recollection. | Tests G2 (verify user claims). User's "I paid with credit card" is contradicted by `payment_history` showing a gift card. |
| 18 | Added: when user asks for refund to original payment method per reservation, agent must use each reservation's original `payment_id`, not consolidate refunds onto one card. | Tests fidelity to explicit user instructions and refusal to fabricate a "system requires single card" rule. |
| 20 | Added: agent must call `search_direct_flight` with airport codes, not city names. | Tests API argument hygiene. City-name queries return empty and waste turns. |
| 20 | Added: when no direct flight exists, agent must search candidate connecting hubs to build a one-stop itinerary. | Tests against premature transfer. The agent has the same multi-leg-search capability used successfully in other tasks. |
| 21 | Added: agent must not repeatedly retry the same failed search; must try alternative routings. | Tests against degenerate retry loops. Re-issuing an identical empty-result query wastes turns and ends in transfer. |
| 23 | Added: agent must not silently shift a connection segment to a different date than the user specified. | Tests fidelity to user-specified dates. A same-day-as-outbound connection is not equivalent to the requested return date. |
| 24 | Added: agent must not transfer for an in-scope cancellation denial on reservation H9ZU1C. | Tests transfer discipline in a multi-task conversation where one task is a clear in-policy denial. |
| 26 | Added: agent must not transfer for reservation 3FRNFB cancellation denial. | Tests transfer discipline under user pressure when the denial is in-scope per policy. |
| 27 | Added: agent must verify HAT039 delay status against flight data, not accept the user's claim. | Tests G2 (verify user claims) for delay context — explicitly flagged as a missing action in the task notes. |
| 27 | Added: agent must not transfer for the in-scope compensation denial (compensation conditional on change/cancel; user refuses both). | Tests transfer discipline in delay-compensation context. |
| 28 | Added: agent must not repeatedly offer to transfer after a clear in-scope denial. | Tests against soft-escalation pattern of repeated "Would you like me to transfer you?" offers. |
| 29 | Added: agent must not silently change destination via `update_reservation_flights` (DTW→LGA → DTW→JFK is destination change, not modification). | Tests rule application of origin/destination immutability. Same pattern as task 13. |
| 31 | Added: agent must not transfer for the basic-economy modification denial; must not promise the human can make exceptions. | Tests G1 + G6 combined. |
| 32 | Added: agent must recognize that basic economy reservations CAN change cabin class. | Tests G4 rule disambiguation. Same pattern as task 7. |
| 35 | Added: when user asks for "second cheapest" and only one direct flight exists, agent must search connecting options before booking. | Tests inference of user intent from quantifiers. "Second cheapest" implies a multi-option comparison. |
| 36 | Added: agent must not tell the user bereavement is covered by travel insurance. | Tests against fabricated insurance coverage. Policy is explicit: insurance covers health or weather reasons only. |
| 36 | Added: agent must recognize EUJUY6 has an already-flown outbound segment (HAT238 on 2024-05-14) and that policy requires transfer, not cancel-and-rebook. | Tests scheduled-date-vs-current-time reasoning on the cancellation path (mirror of task 2's delay-date check). |
| 37 | Added: agent must not transfer for IFOYYZ in-scope denial (NQNU5R transfer is policy-correct because portions flown). | Same per-task transfer framing as task 9. |
| 43 | Added: agent must not transfer for the D1EW9B denial. | Tests transfer discipline; silver membership does not create cancellation eligibility. |
| 44 | Added: agent must not treat "change of plan" as a reason covered by travel insurance. | Tests against fabricated insurance coverage. Same pattern as task 36 (different fabricated reason). |
| 45 | Added: agent must not transfer for reservation PEP4E0 when user has explicitly refused transfer; cancel/modify/add-insurance denials are all in-scope. | Tests transfer discipline against user-refused transfer (same shape as task 6). |
| 46 | Added: agent must not transfer for insurance-refund denial. | Tests transfer discipline for a clear in-scope denial. |
| 47 | Added: agent must not transfer when user has explicitly refused transfer 5x and the cancellation denial is in-scope. | Tests transfer discipline against repeated user refusal. |
| 48 | Added: agent must not transfer when it has already correctly identified that booking is outside the 24-hour window from `created_at`. | Tests against "human can resolve discrepancy" framing for user-misremembering scenarios. |
| 49 | Added: agent must not promise the human agent can "verify payment history" or check for "recording errors" as a way to soften denial of an unverifiable user claim. | Tests against G6 false-promise pattern when user's claim contradicts ground-truth fields. |

No changes to tasks 3, 4, 8, 12, 17, 19, 22, 25, 30, 33, 34, 38, 39, 40, 41, 42 — existing assertions are concrete and well-scoped, agent behavior was clean, or evaluator caught the right failure cleanly.

## Candidate global assertions (not yet applied)

Patterns observed across multiple tasks in the 0–9 sample. Could be promoted to standing assertions applied to every task, instead of duplicated per-task. **Pending decision.**

| ID | Assertion | Tasks hit in sample |
|---|---|---|
| G1 | Agent transfers to human only when (a) request is genuinely out-of-scope, (b) a portion of a flight to be cancelled has already been flown, or (c) the user explicitly asks for transfer / supervisor. | 0, 1, 5, 6, 9, 11, 13, 15, 16, 24, 26, 27, 28, 31, 37, 43, 45, 46, 47, 48 |
| G2 | Agent verifies user claims (delay, cancellation status, membership tier, cabin class, payment method) against available tool data before acting. | 2, 16, 27, 48 |
| G3 | Agent applies all relevant policy facts when reasoning about eligibility, not just the first that yields a denial. | 2 |
| G4 | Agent does not conflate distinct policy rules (e.g., "modify flights" vs "change cabin"; "basic economy modification" vs "origin/destination modification"). | 7, 13, 32 |
| G5 | Agent's reported numerical totals are arithmetically correct and correctly scoped. | 7 |
| G6 | Agent does not make unverifiable promises about what a human agent, supervisor, or other downstream actor can do. | 5, 10, 31, 48, 49 |
| G7 | Agent does not fabricate policy or insurance coverage. Insurance covers health/weather only; payment-method profile-presence is the only constraint on refund destination; bereavement, change-of-plan, and friend's-birthday are not insurance-covered reasons. | 15, 18, 36, 44 |
| G8 | Agent uses API arguments in their canonical form (airport codes, `basic_economy` with underscore), not display strings or city names returned in tool outputs. | 11, 20 |
| G9 | When a search returns empty, agent tries alternative routings or hubs before declaring impossibility. Does not re-issue identical failed queries. | 15, 20, 21, 35 |

## Tone rubric (new, separate from `nl_assertions`)

Scored alongside `nl_assertions` but not folded into the main pass/fail signal. A task can pass the main eval and still fail tone checks. Implementation TBD.

| ID | Check |
|---|---|
| T1 | Asks for all known-required info upfront. When the task requires multiple identifiers (e.g. user ID + reservation ID + reason), agent requests them together in a single turn rather than drip-feeding across consecutive turns. PASSES when the next-needed piece legitimately depends on the answer to the previous one. |
| T2 | No unsolicited policy exposition. Agent states outcomes, not the rulebook. FAILS only when agent recites eligibility criteria or qualification clauses as a numbered/bulleted list (e.g. 'Cancellation is allowed if: 1.X, 2.Y, 3.Z'). PASSES when agent uses lists for user-facing options, data summaries (reservations, flights, totals), action plans, or its own limitations — even with bullets/numbering. |

### Tone rubric revision notes

- **T1 revised (was: "Batched info-gathering: when the agent needs N pieces of info to proceed, it asks for them in one turn, not one-per-turn.")** — original wording let the judge pass any case where only one piece of info was needed per turn, even when the agent could have anticipated all required identifiers upfront. Sharpened to focus on whether the agent drips info across consecutive turns vs. asks for everything it knows it will need at the start.
- **T2 revised (was: "No unsolicited policy exposition: the agent states the outcome to the user, not the rulebook. Quoting policy criteria as numbered/bulleted lists fails this check.")** — original wording caused the judge to flag any bulleted/numbered content in agent output (including user-facing options and data summaries). Sharpened to fail only when the agent recites eligibility/qualification criteria or policy clauses as a list. User-facing option lists, data summaries, and action plans now pass even with bullets.

## Evaluation sanity audit (2026-06-15) — assertion correctness pass

Full pass over all 50 tasks' `nl_assertions`, auditing each for three properties: **satisfiable** with the actual 10-tool surface, **correct** per `policy.md`, and **internally consistent** with the task's own data. Method: four category auditors (cancellation / compensation / modification / booking) cross-referenced each assertion against `policy.md` and `db.json`, then each flagged change was re-verified directly against `db.json` before applying. The judge requires *all* of a task's assertions to pass (`src/eval/judge.py:110`), so a single unsatisfiable or wrong assertion silently fails an otherwise-correct run.

**Key structural finding:** no tool exposes a flight's live status. `search_direct_flight` returns only `available`-status flights (`src/agents/v0/tools.py:122`); `get_reservation_details` carries no per-flight delay/cancellation status. So any assertion demanding the agent "verify the flight was delayed/cancelled against flight data" is **unsatisfiable by construction** — the agent can only reason about a flight's *date* vs the current time (2024-05-15 15:00 EST). These assertions were the dominant defect and the biggest source of false-negative task failures.

### Changes applied

| Task | Assertion | Class | Change |
|---|---|---|---|
| 35 | "Agent charges $290 to credit card credit_card_907483" | BUGGY (truncated id) | id corrected to `credit_card_9074831` (the value in the user's profile / ground-truth action). A literal-match judge failed correct runs. |
| 23 | A3: "...outbound flights HAT023 and HAT204 on 2024-05-26..." | BUGGY (wrong date) | HAT204 (SFO→SEA) is on 2024-05-28, not 05-26 — A3 contradicted A8 ("SFO→SEA must remain on May 28"). Rewritten with correct per-leg dates and the true JFK→SFO→SEA→JFK routing. |
| 39 | A2: "Agent cancels reservation MSJ4OA." | WRONG-PER-POLICY | MSJ4OA is economy + insurance, but the user's reason is "give up the seat" (change of plan), not health/weather — so it is **not** cancellable. Asserting a cancel contradicted the task's own purpose ("only cancel flights eligible for refunds"). Flipped to "does not cancel," with the policy reason stated. |
| 2 | A1: "Agent should check that the flight was indeed delayed." | UNVERIFIABLE | **Removed.** No tool reports delay status; the verifiable version (temporal date check) already exists as A4, so A1 was redundant *and* impossible. |
| 2 | A5: "...apply all relevant policy facts (membership tier, insurance, cabin class)..." | OVER-SPECIFIED | The user is gold (passes the eligibility gate), so the controlling reason for withholding the $50 cert is the change/cancel refusal, not eligibility. Rewritten to check that the agent does **not** deny on eligibility grounds. |
| 4 | A0: "Agent should realize that flight was not cancel and not in business class." | UNVERIFIABLE (partial) | "Not cancelled" is not tool-verifiable. Rewritten to the verifiable proxy: no business-cabin reservation exists (checkable) and a cancellation cannot be confirmed, so the claim is unsupported. |
| 27 | A0: "Agent confirms that flight HAT039 ... has been delayed." | UNVERIFIABLE | Rewritten: agent must NOT assert HAT039 is delayed as fact; HAT039 departs 22:00 EST (after current 15:00 EST) so it hasn't departed — treat as an unconfirmed claim. |
| 27 | A1: "Agent confirms that user can receive compensation because he has Silver status." | WRONG-PER-POLICY | Silver only passes the *eligibility gate*; the $50 delay cert still requires a change/cancel (which the user refuses). A1 contradicted A2. Rewritten to reflect the gate-vs-payout distinction. |
| 27 | A3: "Agent should verify the delay status of HAT039 against available flight data..." | UNVERIFIABLE | **Removed.** Demands an impossible tool action (task `notes` even says "action to check delay should be added" — but no such tool exists). Temporal handling now covered by rewritten A0. |
| 38 | A1: "Agent verifies that the flight was delayed." | UNVERIFIABLE | Rewritten: agent must not accept the delay claim at face value (look up the reservation), but cannot claim to confirm the delay itself — no tool reports it. |
| 20 | A0: "...with flights HAT136 and HAT039 on 2024-05-20..." | OVER-SPECIFIED | At least two one-stop itineraries tie at the optimal $255 fare (JFK→ATL→SEA and EWR→DFW→SEA). Relaxed to accept any $255 one-stop economy itinerary departing after 11:00 EST; the canonical HAT136/HAT039 route is named as the example. Payment assertion (A1) is unchanged — the $255→$250+$5 split is invariant across the ties. |

Net: 164 → 162 assertions (2 unverifiable removed), 9 rewritten/corrected.

### Flagged but NOT changed (needs a decision or is out of assertion scope)

- **Task 44 A4** ("Agent updates KC18K6 to business"): the task *instruction* says upgrade flights "≤3 hours including layovers," but KC18K6's total elapsed time is ~7h (3h + 2h legs + 2h layover) while the ground-truth action upgrades it — implying the intended rule is *per-segment* ≤3h. The ambiguity is in the task instruction, not the assertion. Recommend clarifying the instruction's duration definition.
- **Tasks 11 ($5244) / 18 ($23553)** dollar assertions are the *passenger-multiplied* customer-facing figures and are correct as written, but `update_reservation_flights` records a *per-flight* (non-multiplied) delta in `payment_history` (1748 / 14965). Documented so the gap isn't mistaken for a math error.
- **Task 7 A4 ($1,628)**: correct under the natural reading, but the value is order-dependent (it shifts if the agent upgrades XEHM4B to business before reporting "current cost"). Left as-is; flagged as mildly fragile.
- **Task 12 A1**: grammatically garbled but checks the right rule (uniform cabin across passengers). Cosmetic; left as-is.

### Recommendation (tooling, not assertions)

The recurring unverifiable-delay pattern is the eval's clearest signal that the **tool surface is missing a `get_flight_status(flight_number, date)` (or reservation-flight live status)**. With it, the "confirm the facts before compensation" policy (`policy.md:159`) becomes genuinely checkable and the rewritten temporal-proxy assertions could return to true status verification. This is a v2 (tooling/architecture) change, not a prompting or assertion change — and it is the strongest data-driven motivation for v2.
