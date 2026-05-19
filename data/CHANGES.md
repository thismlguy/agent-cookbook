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
